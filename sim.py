"""
Factory ISAC sensing with Sionna RT.

Reads factory_layout.json + uegnb.json, generates PLY meshes + scene XML,
runs bistatic ISAC to localize AGV targets, writes isac_results.json.

Usage:
    CUDA_VISIBLE_DEVICES='' python sionna.py     # CPU-only (GPU busy)
    python sionna.py                              # uses GPU if available
"""

import os, json, struct, gc, time
import numpy as np

SCENE_DIR = "scene_data"
MESH_DIR  = os.path.join(SCENE_DIR, "meshes")
SCENE_XML = os.path.join(SCENE_DIR, "factory.xml")
C = 3e8

# ── PLY helpers ─────────────────────────────────────────────────────────────────

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

# Panel constructors — winding verified for correct outward normals
def _ps(xa, xb, y, za, zb): return (xa,y,zb),(xa,y,za),(xb,y,za),(xb,y,zb)  # south (normal -y)
def _pn(xa, xb, y, za, zb): return (xb,y,zb),(xb,y,za),(xa,y,za),(xa,y,zb)  # north (normal +y)
def _pw(x, ya, yb, za, zb): return (x,yb,zb),(x,yb,za),(x,ya,za),(x,ya,zb)  # west  (normal -x)
def _pe(x, ya, yb, za, zb): return (x,ya,zb),(x,ya,za),(x,yb,za),(x,yb,zb)  # east  (normal +x)
def _pf(x0, x1, y0, y1):    return (x0,y0,0),(x0,y1,0),(x1,y1,0),(x1,y0,0)  # floor (normal -z)
def _pr(x0, x1, y0, y1, h): return (x0,y0,h),(x1,y0,h),(x1,y1,h),(x0,y1,h)  # roof  (normal +z)

def _split(start, end, doors):
    """Yield (is_gap, a, b, dh) segments along [start,end] with door openings."""
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
        if gap:
            if dh < h: out.append(_ps(a, b, y, dh, h))
        else:
            out.append(_ps(a, b, y, 0, h))
    return out

def _wall_n(x0, x1, y, h, doors):
    out = []
    for gap, a, b, dh in _split(x0, x1, doors):
        if gap:
            if dh < h: out.append(_pn(a, b, y, dh, h))
        else:
            out.append(_pn(a, b, y, 0, h))
    return out

def _wall_w(x, y0, y1, h, doors):
    out = []
    for gap, a, b, dh in _split(y0, y1, doors):
        if gap:
            if dh < h: out.append(_pw(x, a, b, dh, h))
        else:
            out.append(_pw(x, a, b, 0, h))
    return out

def _wall_e(x, y0, y1, h, doors):
    out = []
    for gap, a, b, dh in _split(y0, y1, doors):
        if gap:
            if dh < h: out.append(_pe(x, a, b, dh, h))
        else:
            out.append(_pe(x, a, b, 0, h))
    return out

def _box(x0, x1, y0, y1, h):
    """All 6 faces of a solid box object."""
    return [
        _ps(x0, x1, y0, 0, h), _pn(x0, x1, y1, 0, h),
        _pw(x0, y0, y1, 0, h), _pe(x1, y0, y1, 0, h),
        _pf(x0, x1, y0, y1),   _pr(x0, x1, y0, y1, h),
    ]


# ── Scene generation ─────────────────────────────────────────────────────────────

def generate_scene(layout):
    """Generate PLY meshes + scene XML from layout dict. Returns XML path."""
    os.makedirs(MESH_DIR, exist_ok=True)

    b = layout["building"]
    x0, x1, y0, y1, h = b["x0"], b["x1"], b["y0"], b["y1"], b["height"]
    doors = b.get("doors", {})

    surfaces = []  # (mesh_id, ply_file, material)

    # Ground plane
    _write_ply(os.path.join(MESH_DIR, "ground.ply"), [_pf(x0, x1, y0, y1)])
    surfaces.append(("ground", "ground.ply", "concrete"))

    # Outer walls (split at doors)
    for wname, panels in [
        ("wall_south", _wall_s(x0, x1, y0, h, doors.get("south", []))),
        ("wall_north", _wall_n(x0, x1, y1, h, doors.get("north", []))),
        ("wall_west",  _wall_w(x0, y0, y1, h, doors.get("west",  []))),
        ("wall_east",  _wall_e(x1, y0, y1, h, doors.get("east",  []))),
    ]:
        if panels:
            _write_ply(os.path.join(MESH_DIR, f"{wname}.ply"), panels)
            surfaces.append((wname, f"{wname}.ply", "concrete"))

    # Roof (separate so viewer can toggle it)
    _write_ply(os.path.join(MESH_DIR, "roof.ply"), [_pr(x0, x1, y0, y1, h)])
    surfaces.append(("roof", "roof.ply", "metal"))

    # Interior objects (shelves, machines)
    for obj in layout.get("objects", []):
        oid = obj["id"]
        panels = _box(obj["x0"], obj["x1"], obj["y0"], obj["y1"], obj["height"])
        _write_ply(os.path.join(MESH_DIR, f"{oid}.ply"), panels)
        surfaces.append((oid, f"{oid}.ply", obj.get("material", "metal")))

    # Scene XML
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
    with open(SCENE_XML, "w") as fh:
        fh.write("\n".join(xml_lines))

    print(f"  {len(surfaces)} meshes → {SCENE_XML}")
    return SCENE_XML


# ── ISAC pipeline ────────────────────────────────────────────────────────────────

def cfr_from_paths(paths, sc_freqs):
    """[n_rx, rx_ant, n_tx, tx_ant, SC] complex64."""
    cfr = paths.cfr(frequencies=sc_freqs.astype(np.float32), out_type="drjit")
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    return H[..., 0, :]  # drop time dim


def pair_channel(H_full, tx_i, rx_i):
    """Antenna-averaged scalar channel [SC] for one bistatic pair."""
    return H_full[rx_i, :, tx_i, :, :].mean(axis=(0, 1))


def inject_target(h_clut, tx_pos, rx_pos, tgt_pos, fc, rcs_m2, sc_freqs):
    """Add point-target return using excess bistatic delay (normalize_delays=True)."""
    tx, rx, tp = map(np.array, [tx_pos, rx_pos, tgt_pos])
    d_tx  = np.linalg.norm(tp - tx)
    d_rx  = np.linalg.norm(tp - rx)
    d_dir = np.linalg.norm(rx - tx)
    tau   = (d_tx + d_rx - d_dir) / C
    amp   = np.sqrt(rcs_m2) / (4 * np.pi * d_tx * d_rx)
    freqs = fc + sc_freqs
    return h_clut + (amp * np.exp(-2j * np.pi * freqs * tau)).astype(np.complex64)


def cfar_ca_1d(rp_lin, guard=2, ref=8, pfa=1e-3):
    """Cell-averaging CFAR. Returns list of detected bin indices."""
    eta = ref * (pfa ** (-1.0 / ref) - 1.0)
    n, det = len(rp_lin), []
    for i in range(guard + ref, n - guard - ref):
        left  = rp_lin[i - guard - ref : i - guard]
        right = rp_lin[i + guard + 1   : i + guard + ref + 1]
        noise = (left.sum() + right.sum()) / (2 * ref)
        if rp_lin[i] > eta * noise:
            det.append(i)
    return det


def reconstruct_environment(H_full, gnb_pos, layout, sc_freqs, pairs, range_res):
    """
    Bistatic delay-and-sum backprojection over 3D grid.
    For each grid voxel, sum range-profile intensity across all pairs at the
    corresponding bistatic delay → bright where reflectors (walls/objects) exist.
    Returns list of {x,y,z,i} dicts (top 15% by intensity, max 4000 points).
    """
    b = layout["building"]
    x_max, y_max, h_max = b["x1"], b["y1"], b["height"]
    num_sc = len(sc_freqs)
    scs    = float(sc_freqs[1] - sc_freqs[0])

    xs = np.arange(0.0, x_max + 1.01, 1.0)
    ys = np.arange(0.0, y_max + 1.01, 1.0)
    zs = np.arange(0.0, h_max + 0.51, 1.0)
    XX, YY, ZZ = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([XX.ravel(), YY.ravel(), ZZ.ravel()], axis=1).astype(np.float64)
    N = len(pts)

    intensity = np.zeros(N, dtype=np.float64)

    for tx_i, rx_i in pairs:
        h      = pair_channel(H_full, tx_i, rx_i)
        rp     = np.abs(np.fft.ifft(h, n=num_sc)) ** 2  # power range profile

        tx     = np.array(gnb_pos[tx_i], dtype=np.float64)
        rx     = np.array(gnb_pos[rx_i], dtype=np.float64)
        d_dir  = np.linalg.norm(rx - tx)

        d_tx   = np.linalg.norm(pts - tx, axis=1)
        d_rx   = np.linalg.norm(pts - rx, axis=1)
        bins   = (d_tx + d_rx - d_dir) / range_res   # fractional bin

        # Skip bins 0..3 (direct path + near-sidelobe leakage)
        valid  = (bins >= 4.0) & (bins < num_sc - 1)
        bi     = np.clip(np.floor(bins).astype(int), 0, num_sc - 2)
        bf     = bins - bi

        rp_interp = np.where(valid,
                             rp[bi] * (1.0 - bf) + rp[bi + 1] * bf,
                             0.0)
        intensity += rp_interp

    intensity /= len(pairs)

    # Keep top 15%, then cap at 4000 points ordered by intensity
    thresh = np.percentile(intensity, 85)
    mask   = intensity >= thresh
    pts_k  = pts[mask]
    int_k  = intensity[mask]

    order  = np.argsort(int_k)[::-1][:4000]
    pts_k  = pts_k[order]
    int_k  = int_k[order]

    i_min, i_max = int_k.min(), int_k.max()
    int_n  = (int_k - i_min) / (i_max - i_min + 1e-30)

    return [
        {"x": round(float(p[0]), 1), "y": round(float(p[1]), 1),
         "z": round(float(p[2]), 1), "i": round(float(v), 3)}
        for p, v in zip(pts_k, int_n)
    ]


def grid_localize(gnb_pos, constraints, x_max, y_max, res=0.5):
    """Grid-search localization on bistatic range-sum ellipses."""
    xs = np.arange(0.0, x_max + res, res)
    ys = np.arange(0.0, y_max + res, res)
    XX, YY = np.meshgrid(xs, ys)
    cost = np.zeros_like(XX)
    for tx_i, rx_i, R_meas in constraints:
        tx  = np.array(gnb_pos[tx_i])
        rx  = np.array(gnb_pos[rx_i])
        pts = np.stack([XX, YY, np.full_like(XX, 1.2)], axis=-1)
        R_p = np.linalg.norm(pts - tx, axis=-1) + np.linalg.norm(pts - rx, axis=-1)
        cost += (R_p - R_meas) ** 2
    ij  = np.unravel_index(np.argmin(cost), cost.shape)
    return [float(xs[ij[1]]), float(ys[ij[0]]), 1.2]


def run_isac(scene_xml, layout, uegnb):
    from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver

    fc        = uegnb["frequency_ghz"] * 1e9
    bw_mhz    = uegnb["bandwidth_mhz"]
    gnb_pos   = [g["pos"] for g in uegnb["gnbs"]]
    ue_pos    = [u["pos"] for u in uegnb["ues"]]
    n_gnbs    = len(gnb_pos)
    b         = layout["building"]
    x_max, y_max = b["x1"], b["y1"]

    # NR μ=3 (FR2): 120 kHz SCS → ~3333 SC for 400 MHz
    scs    = 120e3
    num_sc = int(bw_mhz * 1e6 / scs)
    _half  = num_sc // 2
    sc_freqs = np.concatenate([np.arange(-_half, 0), np.arange(1, _half+1)]).astype(np.float64) * scs
    range_res = C / (num_sc * scs)

    # All directed bistatic pairs i→j (i≠j)
    pairs = [(i, j) for i in range(n_gnbs) for j in range(n_gnbs) if i != j]

    print(f"Frequency   : {fc/1e9:.1f} GHz")
    print(f"Bandwidth   : {num_sc * scs / 1e6:.1f} MHz  ({num_sc} SC × {scs/1e3:.0f} kHz)")
    print(f"Range res   : {range_res:.3f} m/bin")
    print(f"gNBs        : {n_gnbs}")
    print(f"UE targets  : {len(ue_pos)}")
    print(f"Pairs       : {len(pairs)}")
    print()

    scene = load_scene(scene_xml)
    scene.frequency = fc

    ant = PlanarArray(num_rows=4, num_cols=4, vertical_spacing=0.5,
                      horizontal_spacing=0.5, pattern="iso", polarization="V")
    scene.tx_array = ant
    scene.rx_array = ant

    RX_OFFSET = 0.01  # 1 cm — avoids degenerate zero-delay paths at co-located TX/RX
    for i, pos in enumerate(gnb_pos):
        scene.add(Transmitter(name=f"tx_{i}", position=pos))
    for i, pos in enumerate(gnb_pos):
        scene.add(Receiver(name=f"rx_{i}", position=[pos[0] + RX_OFFSET, pos[1], pos[2]]))

    print("PathSolver (max_depth=2)...", flush=True)
    t0     = time.time()
    paths  = PathSolver()(scene, max_depth=2)
    H_full = cfr_from_paths(paths, sc_freqs)
    print(f"  Done in {time.time()-t0:.1f}s  shape: {H_full.shape}\n")
    del paths; gc.collect()

    AGV_RCS_M2   = 5.0
    ue_constrs   = [[] for _ in ue_pos]
    pair_results = []

    print("Per-pair CFAR detection:")
    for tx_i, rx_i in pairs:
        h_clut   = pair_channel(H_full, tx_i, rx_i)
        detected = 0
        for k, up in enumerate(ue_pos):
            h_tot  = inject_target(h_clut, gnb_pos[tx_i], gnb_pos[rx_i], up, fc, AGV_RCS_M2, sc_freqs)
            rp_lin = np.abs(np.fft.ifft(h_tot)) ** 2
            peaks  = cfar_ca_1d(rp_lin)

            R_bi  = (np.linalg.norm(np.array(up) - np.array(gnb_pos[tx_i]))
                   + np.linalg.norm(np.array(up) - np.array(gnb_pos[rx_i])))
            R_dir = np.linalg.norm(np.array(gnb_pos[rx_i]) - np.array(gnb_pos[tx_i]))
            bin_th = (R_bi - R_dir) / range_res

            for pk in peaks:
                if abs(pk - bin_th) <= 2.0:
                    ue_constrs[k].append((tx_i, rx_i, R_bi))
                    detected += 1
                    break

        print(f"  gNB-{tx_i}→gNB-{rx_i}: {detected}/{len(ue_pos)} detected")
        pair_results.append({"tx": tx_i, "rx": rx_i, "detections": detected})

    print("\n=== Localization ===")
    print(f"  {'UE':>4}  {'True(x,y)':>14}  {'Est(x,y)':>14}  {'Err(m)':>7}  {'Pairs':>5}")
    print("  " + "─" * 50)
    loc_results = []
    for k, up in enumerate(ue_pos):
        c = ue_constrs[k]
        if len(c) >= 3:
            est = grid_localize(gnb_pos, c, x_max, y_max)
            err = float(np.linalg.norm(np.array(up[:2]) - np.array(est[:2])))
        else:
            est, err = None, float("nan")

        ts = f"({up[0]:.1f},{up[1]:.1f})"
        es = f"({est[0]:.1f},{est[1]:.1f})" if est else "N/A"
        er = f"{err:.2f}" if not np.isnan(err) else "—"
        print(f"  UE-{k:<3}  {ts:>14}  {es:>14}  {er:>7}  {len(c):>5}")

        loc_results.append({
            "ue_idx":    k,
            "ue_type":   uegnb["ues"][k]["type"],
            "true_pos":  up,
            "est_pos":   est,
            "error_m":   round(err, 3) if not np.isnan(err) else None,
            "num_pairs": len(c),
        })

    n_loc  = sum(1 for r in loc_results if r["est_pos"])
    errors = [r["error_m"] for r in loc_results if r["error_m"] is not None]

    print(f"\n  Localized : {n_loc}/{len(ue_pos)}")
    if errors:
        print(f"  Mean err  : {np.mean(errors):.2f} m")
        print(f"  Max err   : {np.max(errors):.2f} m")

    print("\n=== Environment Reconstruction ===")
    print("  Backprojecting clutter returns onto 3D grid...", flush=True)
    t_recon = time.time()
    env_pts = reconstruct_environment(H_full, gnb_pos, layout, sc_freqs, pairs, range_res)
    print(f"  {len(env_pts)} voxels above threshold in {time.time()-t_recon:.1f}s")

    out = {
        "frequency_ghz":    fc / 1e9,
        "bandwidth_mhz":    round(num_sc * scs / 1e6, 1),
        "range_res_m":      round(range_res, 4),
        "agv_rcs_m2":       AGV_RCS_M2,
        "n_gnbs":           n_gnbs,
        "n_ues":            len(ue_pos),
        "gnb_positions":    gnb_pos,
        "ue_localization":  loc_results,
        "pair_results":     pair_results,
        "n_localized":      n_loc,
        "mean_error_m":     round(float(np.mean(errors)), 3) if errors else None,
        "max_error_m":      round(float(np.max(errors)),  3) if errors else None,
        "env_reconstruction": env_pts,
    }
    with open("isac_results.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\n  Results → isac_results.json")
    return out


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=== Factory ISAC ===\n")

    with open("factory_layout.json") as fh:
        layout = json.load(fh)
    with open("uegnb.json") as fh:
        uegnb = json.load(fh)

    print("Generating scene...")
    xml = generate_scene(layout)
    print()

    run_isac(xml, layout, uegnb)
    print(f"\nTotal runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
