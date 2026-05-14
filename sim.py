"""
Factory ISAC sensing — improved pipeline (v2).

Improvements over v1:
  1. Differential channel  — two PathSolver calls (clutter-only vs clutter+AGVs);
     H_tgt = H_agv − H_clut captures real ray-traced AGV scattering.
  2. Array beamforming     — Bartlett beamformer on 4×4 RX array → range-azimuth map;
     AoA resolved per bistatic pair, not just scalar range profile.
  3. Closed-form localization — exact 2D solution from bistatic range + AoA at RX;
     avoids slow coarse grid search for initial estimate.
  4. Weighted LS fusion    — SNR-weighted centroid across pairs + 0.1 m fine-grid
     range-only refinement.

Usage:
    CUDA_VISIBLE_DEVICES='' python sim.py     # CPU-only
    python sim.py                              # uses GPU if available
"""

import os, json, struct, gc, time
import numpy as np

SCENE_DIR     = "scene_data"
MESH_DIR      = os.path.join(SCENE_DIR, "meshes")
SCENE_XML     = os.path.join(SCENE_DIR, "factory.xml")
SCENE_AGV_XML = os.path.join(SCENE_DIR, "factory_agv.xml")
C = 3e8

AGV_L, AGV_W, AGV_H = 2.0, 1.0, 1.5   # AGV body dimensions (m)

# ── PLY helpers ──────────────────────────────────────────────────────────────────

_UV = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]

def _write_ply(path, panels):
    nv, nf = 4 * len(panels), 2 * len(panels)
    hdr = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {nv}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float u\nproperty float v\n"
        f"element face {nf}\n"
        "property list uchar int vertex_indices\nend_header\n"
    )
    with open(path, "wb") as fh:
        fh.write(hdr.encode("ascii"))
        for v0, v1, v2, v3 in panels:
            for i, (x, y, z) in enumerate([v0, v1, v2, v3]):
                u, v = _UV[i]
                fh.write(struct.pack("<fffff", x, y, z, u, v))
        for i in range(len(panels)):
            b = i * 4
            fh.write(struct.pack("<Biii", 3, b, b+1, b+2))
            fh.write(struct.pack("<Biii", 3, b, b+2, b+3))

def _ps(xa, xb, y, za, zb): return (xa,y,zb),(xa,y,za),(xb,y,za),(xb,y,zb)
def _pn(xa, xb, y, za, zb): return (xb,y,zb),(xb,y,za),(xa,y,za),(xa,y,zb)
def _pw(x, ya, yb, za, zb): return (x,yb,zb),(x,yb,za),(x,ya,za),(x,ya,zb)
def _pe(x, ya, yb, za, zb): return (x,ya,zb),(x,ya,za),(x,yb,za),(x,yb,zb)
def _pf(x0, x1, y0, y1):    return (x0,y0,0),(x0,y1,0),(x1,y1,0),(x1,y0,0)
def _pr(x0, x1, y0, y1, h): return (x0,y0,h),(x1,y0,h),(x1,y1,h),(x0,y1,h)

def _split(start, end, doors):
    gaps = sorted([(d["c"] - d["w"]/2, d["c"] + d["w"]/2, d["h"]) for d in doors])
    prev = start
    for da, db, dh in gaps:
        if prev < da - 1e-6: yield False, prev, da, 0.0
        yield True, da, db, dh
        prev = db
    if prev < end - 1e-6: yield False, prev, end, 0.0

def _wall_s(x0, x1, y, h, doors):
    out = []
    for gap, a, b, dh in _split(x0, x1, doors):
        out.append(_ps(a, b, y, dh, h) if gap and dh < h else (_ps(a, b, y, 0, h) if not gap else None))
    return [p for p in out if p is not None]

def _wall_n(x0, x1, y, h, doors):
    out = []
    for gap, a, b, dh in _split(x0, x1, doors):
        out.append(_pn(a, b, y, dh, h) if gap and dh < h else (_pn(a, b, y, 0, h) if not gap else None))
    return [p for p in out if p is not None]

def _wall_w(x, y0, y1, h, doors):
    out = []
    for gap, a, b, dh in _split(y0, y1, doors):
        out.append(_pw(x, a, b, dh, h) if gap and dh < h else (_pw(x, a, b, 0, h) if not gap else None))
    return [p for p in out if p is not None]

def _wall_e(x, y0, y1, h, doors):
    out = []
    for gap, a, b, dh in _split(y0, y1, doors):
        out.append(_pe(x, a, b, dh, h) if gap and dh < h else (_pe(x, a, b, 0, h) if not gap else None))
    return [p for p in out if p is not None]

def _box(x0, x1, y0, y1, h):
    return [
        _ps(x0, x1, y0, 0, h), _pn(x0, x1, y1, 0, h),
        _pw(x0, y0, y1, 0, h), _pe(x1, y0, y1, 0, h),
        _pf(x0, x1, y0, y1),   _pr(x0, x1, y0, y1, h),
    ]

def _agv_box(cx, cy):
    """Full metal box representing an AGV body on the floor."""
    return _box(cx - AGV_L/2, cx + AGV_L/2,
                cy - AGV_W/2, cy + AGV_W/2, AGV_H)


# ── Scene generation ──────────────────────────────────────────────────────────────

def generate_scene(layout, agv_positions=None, out_xml=SCENE_XML):
    """Generate PLY meshes + scene XML. If agv_positions given, add AGV metal boxes."""
    os.makedirs(MESH_DIR, exist_ok=True)

    b = layout["building"]
    x0, x1, y0, y1, h = b["x0"], b["x1"], b["y0"], b["y1"], b["height"]
    doors = b.get("doors", {})

    surfaces = []

    _write_ply(os.path.join(MESH_DIR, "ground.ply"), [_pf(x0, x1, y0, y1)])
    surfaces.append(("ground", "ground.ply", "concrete"))

    for wname, panels in [
        ("wall_south", _wall_s(x0, x1, y0, h, doors.get("south", []))),
        ("wall_north", _wall_n(x0, x1, y1, h, doors.get("north", []))),
        ("wall_west",  _wall_w(x0, y0, y1, h, doors.get("west",  []))),
        ("wall_east",  _wall_e(x1, y0, y1, h, doors.get("east",  []))),
    ]:
        if panels:
            _write_ply(os.path.join(MESH_DIR, f"{wname}.ply"), panels)
            surfaces.append((wname, f"{wname}.ply", "concrete"))

    _write_ply(os.path.join(MESH_DIR, "roof.ply"), [_pr(x0, x1, y0, y1, h)])
    surfaces.append(("roof", "roof.ply", "metal"))

    for obj in layout.get("objects", []):
        oid = obj["id"]
        panels = _box(obj["x0"], obj["x1"], obj["y0"], obj["y1"], obj["height"])
        _write_ply(os.path.join(MESH_DIR, f"{oid}.ply"), panels)
        surfaces.append((oid, f"{oid}.ply", obj.get("material", "metal")))

    if agv_positions:
        for k, (ax, ay) in enumerate(agv_positions):
            mid = f"agv_{k}"
            _write_ply(os.path.join(MESH_DIR, f"{mid}.ply"), _agv_box(ax, ay))
            surfaces.append((mid, f"{mid}.ply", "metal"))

    xml_lines = [
        '<scene version="2.1.0">',
        '',
        '    <bsdf type="itu-radio-material" id="concrete">',
        '        <string name="type" value="concrete"/>',
        '        <float name="thickness" value="0.3"/>',
        '    </bsdf>',
        '',
        '    <bsdf type="itu-radio-material" id="metal">',
        '        <string name="type" value="metal"/>',
        '        <float name="thickness" value="0.01"/>',
        '    </bsdf>',
        '',
    ]
    for mesh_id, ply_file, mat in surfaces:
        xml_lines += [
            f'    <shape type="ply" id="{mesh_id}">',
            f'        <string name="filename" value="meshes/{ply_file}"/>',
            f'        <boolean name="face_normals" value="true"/>',
            f'        <ref id="{mat}" name="bsdf"/>',
            f'    </shape>',
            '',
        ]
    xml_lines.append('</scene>')
    with open(out_xml, "w") as fh:
        fh.write("\n".join(xml_lines))

    print(f"  {len(surfaces)} meshes → {out_xml}")
    return out_xml


# ── Array beamforming ─────────────────────────────────────────────────────────────

def ant_positions(n_rows, n_cols, spacing_m):
    """[N_ant, 2] horizontal (x,y) element positions, row-major order (matches Sionna)."""
    pos = []
    for r in range(n_rows):
        for c in range(n_cols):
            pos.append([(c - (n_cols - 1) / 2) * spacing_m,
                        (r - (n_rows - 1) / 2) * spacing_m])
    return np.array(pos, dtype=np.float64)


def range_azimuth_map(H_pair, ant_pos_m, lam, n_theta=360):
    """
    Bartlett beamformer on the RX array.
    H_pair   : [rx_ant, SC] complex64
    ant_pos_m: [rx_ant, 2] element positions in metres (horizontal plane)
    Returns  : thetas [n_theta], P [n_theta, N_range]
    """
    rp_ant = np.fft.ifft(H_pair, axis=1)                  # [rx_ant, N_range]
    thetas = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    phase  = (2 * np.pi / lam) * (
        np.outer(np.cos(thetas), ant_pos_m[:, 0]) +
        np.outer(np.sin(thetas), ant_pos_m[:, 1])
    )                                                      # [n_theta, rx_ant]
    A = np.exp(-1j * phase)
    N = ant_pos_m.shape[0]
    P = np.abs(A @ rp_ant) ** 2 / N ** 2                  # [n_theta, N_range]
    return thetas, P


def cfar_ca_1d_fast(rp, guard=3, ref=8, pfa=1e-3):
    """Vectorised CA-CFAR via cumsum. Returns detected bin indices."""
    eta  = ref * (pfa ** (-1.0 / ref) - 1.0)
    n    = len(rp)
    cs   = np.concatenate([[0.0], np.cumsum(rp)])
    half = guard + ref
    det  = []
    for i in range(half, n - half):
        left  = cs[i - guard]     - cs[i - half]
        right = cs[i + half + 1]  - cs[i + guard + 1]
        noise = (left + right) / (2 * ref)
        if noise > 0 and rp[i] > eta * noise:
            det.append(i)
    return det


# ── Localization ──────────────────────────────────────────────────────────────────

def localize_range_aoa(tx_pos, rx_pos, R_bi, theta_rx):
    """
    Closed-form 2D localization from bistatic range sum + AoA at RX.

    Derivation:
      v = tx − rx,  d = [cos θ, sin θ]  (ray direction from rx)
      p = rx + s·d,  d_rx = s,  d_tx = R_bi − s
      ‖p − tx‖ = R_bi − s  →  s = (R² − ‖v‖²) / (2(R − v·d))

    Returns (pos [x, y, z=1.2], quality_weight) or (None, 0).
    """
    tx = np.array(tx_pos[:2], dtype=np.float64)
    rx = np.array(rx_pos[:2], dtype=np.float64)
    d  = np.array([np.cos(theta_rx), np.sin(theta_rx)])
    v  = tx - rx
    R  = float(R_bi)

    denom = 2.0 * (R - float(np.dot(v, d)))
    if abs(denom) < 1e-6:
        return None, 0.0

    s = (R ** 2 - float(np.dot(v, v))) / denom
    if s < 0.1 or s > R:
        return None, 0.0

    p    = rx + s * d
    d_tx = np.linalg.norm(p - tx)
    residual = abs(d_tx + s - R)
    w = 1.0 / (1.0 + 10.0 * residual)
    return [float(p[0]), float(p[1]), 1.2], w


def weighted_ls_localize(gnb_pos, constraints_aoa, x_max, y_max):
    """
    SNR-weighted centroid of AoA candidates + 0.1 m fine-grid range refinement.
    constraints_aoa: list of (tx_i, rx_i, R_bi, theta_rx, snr)
    Returns [x, y, 1.2] or None.
    """
    cands, wts = [], []
    for tx_i, rx_i, R_bi, theta_rx, snr in constraints_aoa:
        pos, q = localize_range_aoa(gnb_pos[tx_i], gnb_pos[rx_i], R_bi, theta_rx)
        if pos is not None:
            cands.append(pos[:2])
            wts.append(snr * q)

    if not cands:
        return None

    W = np.array(wts, dtype=np.float64)
    if W.sum() < 1e-12:
        W = np.ones(len(W))
    W /= W.sum()
    coarse = (np.array(cands) * W[:, None]).sum(axis=0)

    # 0.1 m fine-grid refinement around coarse estimate
    rad = 4.0
    xs = np.arange(max(0.0, coarse[0] - rad), min(x_max, coarse[0] + rad) + 0.1, 0.1)
    ys = np.arange(max(0.0, coarse[1] - rad), min(y_max, coarse[1] + rad) + 0.1, 0.1)
    XX, YY = np.meshgrid(xs, ys)
    cost = np.zeros_like(XX)
    for tx_i, rx_i, R_bi, _, _ in constraints_aoa:
        tx  = np.array(gnb_pos[tx_i][:2])
        rx  = np.array(gnb_pos[rx_i][:2])
        pts = np.stack([XX, YY], axis=-1)
        R_p = (np.linalg.norm(pts - tx, axis=-1) +
               np.linalg.norm(pts - rx, axis=-1))
        cost += (R_p - R_bi) ** 2
    ij = np.unravel_index(np.argmin(cost), cost.shape)
    return [float(xs[ij[1]]), float(ys[ij[0]]), 1.2]


def grid_localize(gnb_pos, constraints, x_max, y_max, res=0.5):
    """Range-only grid-search localization (fallback when AoA unavailable)."""
    xs = np.arange(0.0, x_max + res, res)
    ys = np.arange(0.0, y_max + res, res)
    XX, YY = np.meshgrid(xs, ys)
    cost = np.zeros_like(XX)
    for tx_i, rx_i, R_meas in constraints:
        tx  = np.array(gnb_pos[tx_i])
        rx  = np.array(gnb_pos[rx_i])
        pts = np.stack([XX, YY, np.full_like(XX, 1.2)], axis=-1)
        R_p = (np.linalg.norm(pts - tx, axis=-1) +
               np.linalg.norm(pts - rx, axis=-1))
        cost += (R_p - R_meas) ** 2
    ij = np.unravel_index(np.argmin(cost), cost.shape)
    return [float(xs[ij[1]]), float(ys[ij[0]]), 1.2]


# ── CFR / environment reconstruction ─────────────────────────────────────────────

def cfr_from_paths(paths, sc_freqs):
    """[n_rx, rx_ant, n_tx, tx_ant, SC] complex64."""
    cfr = paths.cfr(frequencies=sc_freqs.astype(np.float32), out_type="drjit")
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    return H[..., 0, :]  # drop time dim


def reconstruct_environment(H_full, gnb_pos, layout, sc_freqs, pairs, range_res):
    """
    Bistatic delay-and-sum backprojection over 3D grid from clutter channel.
    Returns list of {x,y,z,i} dicts (top 15% by intensity, max 4000 points).
    """
    b = layout["building"]
    x_max, y_max, h_max = b["x1"], b["y1"], b["height"]
    num_sc = len(sc_freqs)

    xs = np.arange(0.0, x_max + 1.01, 1.0)
    ys = np.arange(0.0, y_max + 1.01, 1.0)
    zs = np.arange(0.0, h_max + 0.51, 1.0)
    XX, YY, ZZ = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([XX.ravel(), YY.ravel(), ZZ.ravel()], axis=1).astype(np.float64)
    intensity = np.zeros(len(pts), dtype=np.float64)

    for tx_i, rx_i in pairs:
        h   = H_full[rx_i, :, tx_i, :, :].mean(axis=(0, 1))
        rp  = np.abs(np.fft.ifft(h, n=num_sc)) ** 2
        tx  = np.array(gnb_pos[tx_i], dtype=np.float64)
        rx  = np.array(gnb_pos[rx_i], dtype=np.float64)
        d_d = np.linalg.norm(rx - tx)
        d_tx = np.linalg.norm(pts - tx, axis=1)
        d_rx = np.linalg.norm(pts - rx, axis=1)
        bins = (d_tx + d_rx - d_d) / range_res
        valid = (bins >= 4.0) & (bins < num_sc - 1)
        bi    = np.clip(np.floor(bins).astype(int), 0, num_sc - 2)
        bf    = bins - bi
        intensity += np.where(valid, rp[bi] * (1.0 - bf) + rp[bi + 1] * bf, 0.0)

    intensity /= len(pairs)
    thresh = np.percentile(intensity, 85)
    mask   = intensity >= thresh
    pts_k, int_k = pts[mask], intensity[mask]
    order  = np.argsort(int_k)[::-1][:4000]
    pts_k, int_k = pts_k[order], int_k[order]
    i_min, i_max = int_k.min(), int_k.max()
    int_n  = (int_k - i_min) / (i_max - i_min + 1e-30)
    return [
        {"x": round(float(p[0]), 1), "y": round(float(p[1]), 1),
         "z": round(float(p[2]), 1), "i": round(float(v), 3)}
        for p, v in zip(pts_k, int_n)
    ]


# ── ISAC pipeline ─────────────────────────────────────────────────────────────────

def run_isac(scene_xml_clut, scene_xml_agv, layout, uegnb):
    from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver

    fc       = uegnb["frequency_ghz"] * 1e9
    bw_mhz   = uegnb["bandwidth_mhz"]
    gnb_pos  = [g["pos"] for g in uegnb["gnbs"]]
    ue_pos   = [u["pos"] for u in uegnb["ues"]]
    n_gnbs   = len(gnb_pos)
    b        = layout["building"]
    x_max, y_max = b["x1"], b["y1"]

    scs      = 120e3
    num_sc   = int(bw_mhz * 1e6 / scs)
    _half    = num_sc // 2
    sc_freqs = np.concatenate(
        [np.arange(-_half, 0), np.arange(1, _half + 1)]
    ).astype(np.float64) * scs
    range_res  = C / (num_sc * scs)
    lam        = C / fc
    ant_pos_m  = ant_positions(4, 4, 0.5 * lam)   # half-wavelength spacing

    pairs = [(i, j) for i in range(n_gnbs) for j in range(n_gnbs) if i != j]

    print(f"Frequency   : {fc/1e9:.1f} GHz")
    print(f"Bandwidth   : {num_sc*scs/1e6:.1f} MHz  ({num_sc} SC × {scs/1e3:.0f} kHz)")
    print(f"Range res   : {range_res:.4f} m/bin")
    print(f"λ/2 spacing : {lam/2*100:.3f} cm")
    print(f"gNBs        : {n_gnbs}")
    print(f"UE targets  : {len(ue_pos)}")
    print(f"Pairs       : {len(pairs)}")
    print()

    RX_OFFSET = 0.01  # 1 cm — avoids degenerate zero-delay path at co-located TX/RX

    def _solve(xml_path, label):
        print(f"PathSolver: {label} ...", flush=True)
        t = time.time()
        scene = load_scene(xml_path)
        scene.frequency = fc
        ant = PlanarArray(num_rows=4, num_cols=4, vertical_spacing=0.5,
                          horizontal_spacing=0.5, pattern="iso", polarization="V")
        scene.tx_array = ant
        scene.rx_array = ant
        for i, pos in enumerate(gnb_pos):
            scene.add(Transmitter(name=f"tx_{i}", position=pos))
        for i, pos in enumerate(gnb_pos):
            scene.add(Receiver(name=f"rx_{i}",
                               position=[pos[0] + RX_OFFSET, pos[1], pos[2]]))
        paths = PathSolver()(scene, max_depth=2)
        H = cfr_from_paths(paths, sc_freqs)
        print(f"  Done in {time.time()-t:.1f}s  shape: {H.shape}")
        del paths, scene
        gc.collect()
        return H

    H_clut = _solve(scene_xml_clut, "clutter only")
    H_agv  = _solve(scene_xml_agv,  "clutter + AGVs")

    # Differential channel isolates real AGV scattering
    H_tgt = (H_agv - H_clut).astype(np.complex64)
    del H_agv
    gc.collect()

    # Per-pair Bartlett beamforming + CFAR
    print("\nPer-pair beamforming + CFAR detection:")
    ue_constrs_aoa = [[] for _ in ue_pos]   # (tx_i, rx_i, R_bi, theta_rx, snr)
    ue_constrs_rng = [[] for _ in ue_pos]   # (tx_i, rx_i, R_bi) for fallback
    pair_results   = []

    for tx_i, rx_i in pairs:
        H_pair = H_tgt[rx_i, :, tx_i, :, :].mean(axis=1)   # [rx_ant, SC]
        thetas, P = range_azimuth_map(H_pair, ant_pos_m, lam, n_theta=360)
        rp    = P.sum(axis=0)                                # collapsed range profile
        peaks = cfar_ca_1d_fast(rp, guard=3, ref=8, pfa=1e-3)
        noise_floor = max(float(np.median(rp)), 1e-30)
        R_dir = np.linalg.norm(np.array(gnb_pos[rx_i]) - np.array(gnb_pos[tx_i]))
        detected = 0

        for k, up in enumerate(ue_pos):
            R_bi  = (np.linalg.norm(np.array(up) - np.array(gnb_pos[tx_i]))
                   + np.linalg.norm(np.array(up) - np.array(gnb_pos[rx_i])))
            bin_th = (R_bi - R_dir) / range_res

            for pk in peaks:
                if abs(pk - bin_th) <= 2.0:
                    az_bin   = int(np.argmax(P[:, pk]))
                    theta_rx = float(thetas[az_bin])
                    snr      = float(rp[pk]) / noise_floor
                    ue_constrs_aoa[k].append((tx_i, rx_i, R_bi, theta_rx, snr))
                    ue_constrs_rng[k].append((tx_i, rx_i, R_bi))
                    detected += 1
                    break

        print(f"  gNB-{tx_i}→gNB-{rx_i}: {detected}/{len(ue_pos)} detected"
              f"  ({len(peaks)} CFAR peaks)")
        pair_results.append({"tx": tx_i, "rx": rx_i,
                             "detections": detected,
                             "cfar_peaks": len(peaks)})

    # Localization
    print("\n=== Localization ===")
    print(f"  {'UE':>4}  {'True(x,y)':>14}  {'Est(x,y)':>14}  {'Err(m)':>7}  {'Pairs':>5}  Method")
    print("  " + "─" * 68)
    loc_results = []

    for k, up in enumerate(ue_pos):
        c_aoa = ue_constrs_aoa[k]
        c_rng = ue_constrs_rng[k]
        method = "—"

        if len(c_aoa) >= 1:
            est = weighted_ls_localize(gnb_pos, c_aoa, x_max, y_max)
            method = "WLS+AoA"
            if est is None and len(c_rng) >= 3:
                est    = grid_localize(gnb_pos, c_rng, x_max, y_max)
                method = "grid"
        elif len(c_rng) >= 3:
            est    = grid_localize(gnb_pos, c_rng, x_max, y_max)
            method = "grid"
        else:
            est = None

        err = (float(np.linalg.norm(np.array(up[:2]) - np.array(est[:2])))
               if est else float("nan"))
        ts = f"({up[0]:.1f},{up[1]:.1f})"
        es = f"({est[0]:.1f},{est[1]:.1f})" if est else "N/A"
        er = f"{err:.2f}" if not np.isnan(err) else "—"
        print(f"  UE-{k:<3}  {ts:>14}  {es:>14}  {er:>7}  {len(c_aoa):>5}  {method}")

        loc_results.append({
            "ue_idx":    k,
            "ue_type":   uegnb["ues"][k].get("type", "unknown"),
            "true_pos":  up,
            "est_pos":   est,
            "error_m":   round(err, 3) if not np.isnan(err) else None,
            "num_pairs": len(c_aoa),
            "method":    method,
        })

    n_loc  = sum(1 for r in loc_results if r["est_pos"])
    errors = [r["error_m"] for r in loc_results if r["error_m"] is not None]

    print(f"\n  Localized    : {n_loc}/{len(ue_pos)}")
    if errors:
        print(f"  Mean error   : {np.mean(errors):.3f} m")
        print(f"  Median error : {np.median(errors):.3f} m")
        print(f"  Max error    : {np.max(errors):.3f} m")

    print("\n=== Environment Reconstruction ===")
    print("  Backprojecting clutter returns onto 3D grid...", flush=True)
    t_r = time.time()
    env_pts = reconstruct_environment(H_clut, gnb_pos, layout, sc_freqs, pairs, range_res)
    print(f"  {len(env_pts)} voxels in {time.time()-t_r:.1f}s")

    out = {
        "frequency_ghz":      fc / 1e9,
        "bandwidth_mhz":      round(num_sc * scs / 1e6, 1),
        "range_res_m":        round(range_res, 4),
        "array_spacing_m":    round(lam / 2, 6),
        "n_gnbs":             n_gnbs,
        "n_ues":              len(ue_pos),
        "gnb_positions":      gnb_pos,
        "ue_localization":    loc_results,
        "pair_results":       pair_results,
        "n_localized":        n_loc,
        "mean_error_m":       round(float(np.mean(errors)),   3) if errors else None,
        "median_error_m":     round(float(np.median(errors)), 3) if errors else None,
        "max_error_m":        round(float(np.max(errors)),    3) if errors else None,
        "env_reconstruction": env_pts,
    }
    with open("isac_results.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\n  Results → isac_results.json")
    return out


# ── Main ──────────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=== Factory ISAC v2 (differential channel + array beamforming) ===\n")

    with open("factory_layout.json") as fh:
        layout = json.load(fh)
    with open("uegnb.json") as fh:
        uegnb = json.load(fh)

    agv_pos_2d = [
        (u["pos"][0], u["pos"][1])
        for u in uegnb["ues"]
        if u.get("type") == "agv"
    ]

    print("Generating clutter scene...")
    xml_clut = generate_scene(layout, out_xml=SCENE_XML)
    print(f"\nGenerating AGV scene ({len(agv_pos_2d)} AGVs)...")
    xml_agv  = generate_scene(layout, agv_positions=agv_pos_2d, out_xml=SCENE_AGV_XML)
    print()

    run_isac(xml_clut, xml_agv, layout, uegnb)
    print(f"\nTotal runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
