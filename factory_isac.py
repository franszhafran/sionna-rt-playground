"""
Bistatic ISAC sensing — car factory.

Single PathSolver call (matching factory_sim.py pattern). All gNBs act
as TX and RX simultaneously. RX nodes are offset 1 cm from TX nodes to
avoid degenerate zero-delay paths at co-located positions.

Clutter: Sionna RT ray tracing (walls, floor reflections).
Targets:  AGV returns injected analytically via radar equation.
Detection: 1D CA-CFAR per bistatic pair.
Localization: grid-search on bistatic range-sum ellipses.

Outputs: isac_results.json
"""

import json
import gc
import time
import numpy as np
import torch
import sionna.rt.scene as scenes
from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver

from config_schema import load_config

# ── OFDM parameters (must match factory_sim.py) ───────────────────────────────
SUBCARRIER_SPACING = 30e3
NUM_RBS            = 51
SUBCARRIERS_PER_RB = 12
NUM_ACTIVE_SC      = NUM_RBS * SUBCARRIERS_PER_RB   # 612
_half              = NUM_ACTIVE_SC // 2
SC_FREQ_OFFSETS    = np.concatenate(
    [np.arange(-_half, 0), np.arange(1, _half + 1)]
).astype(np.float64) * SUBCARRIER_SPACING

C   = 3e8
BW  = NUM_ACTIVE_SC * SUBCARRIER_SPACING            # ≈ 18.36 MHz
RANGE_SUM_PER_BIN = C / BW                          # ≈ 16.3 m / bin

# ── Bistatic pairs (same-building only) ───────────────────────────────────────
BISTATIC_PAIRS = [
    (0, 1),                           # Stamping Plant
    (2, 3), (3, 4), (2, 4),           # Body Shop
    (5, 6),                           # Paint Shop
    (7, 8), (8, 9), (9, 10),          # General Assembly
    (7, 9), (8, 10), (7, 10),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def cfr_from_paths(paths):
    """[num_gnbs, rx_ant, num_gnbs, tx_ant, SC] complex64."""
    cfr = paths.cfr(
        frequencies=SC_FREQ_OFFSETS.astype(np.float32),
        out_type="drjit",
    )
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    return H[..., 0, :]   # drop time dim


def pair_channel(H_full, tx_i, rx_i):
    """Antenna-averaged scalar channel [SC] for one bistatic pair."""
    return H_full[rx_i, :, tx_i, :, :].mean(axis=(0, 1))


def inject_target(h_clut, tx_pos, rx_pos, tgt_pos, fc, rcs_m2):
    """
    Add point-target return onto clutter channel.
    Uses excess delay (τ_bistatic − τ_direct) matching Sionna normalize_delays=True.
    """
    tx = np.array(tx_pos, np.float64)
    rx = np.array(rx_pos, np.float64)
    tp = np.array(tgt_pos, np.float64)

    d_tx    = np.linalg.norm(tp - tx)
    d_rx    = np.linalg.norm(tp - rx)
    d_dir   = np.linalg.norm(rx - tx)
    tau_exc = (d_tx + d_rx - d_dir) / C

    amp   = np.sqrt(rcs_m2) / (4 * np.pi * d_tx * d_rx)
    freqs = fc + SC_FREQ_OFFSETS
    h_tgt = (amp * np.exp(-2j * np.pi * freqs * tau_exc)).astype(np.complex64)
    return h_clut + h_tgt


def cfar_ca_1d(rp_lin, guard=3, ref=10, pfa=1e-4):
    """Cell-averaging CFAR. Returns list of detected bin indices."""
    eta = ref * (pfa ** (-1.0 / ref) - 1.0)
    n   = len(rp_lin)
    det = []
    for i in range(guard + ref, n - guard - ref):
        left  = rp_lin[i - guard - ref : i - guard]
        right = rp_lin[i + guard + 1   : i + guard + ref + 1]
        noise = (left.sum() + right.sum()) / (2 * ref)
        if rp_lin[i] > eta * noise:
            det.append(i)
    return det


def grid_localize(gnb_positions, constraints, res=5.0):
    """
    Least-squares grid search over factory floor.
    constraints: list of (tx_i, rx_i, R_meas) where R_meas = d_tx + d_rx in m.
    Returns (est_xyz, rms_m).
    """
    xs = np.arange(0.0, 251.0, res)
    ys = np.arange(0.0, 161.0, res)
    XX, YY = np.meshgrid(xs, ys)
    cost   = np.zeros_like(XX, np.float64)

    for tx_i, rx_i, R_meas in constraints:
        tx  = np.array(gnb_positions[tx_i], np.float64)
        rx  = np.array(gnb_positions[rx_i], np.float64)
        pts = np.stack([XX, YY, np.full_like(XX, 1.5)], axis=-1)
        R_p = np.linalg.norm(pts - tx, axis=-1) + np.linalg.norm(pts - rx, axis=-1)
        cost += (R_p - R_meas) ** 2

    ij  = np.unravel_index(np.argmin(cost), cost.shape)
    est = [float(xs[ij[1]]), float(ys[ij[0]]), 1.5]
    rms = float(np.sqrt(cost[ij] / max(len(constraints), 1)))
    return est, rms


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Bistatic ISAC Sensing ===\n")
    t0 = time.time()

    config = load_config("config.json")
    with open("config.json") as f:
        raw = json.load(f)

    ue_types      = raw.get("ue_types", [])
    ue_positions  = config.static_receivers
    gnb_positions = config.transmitters
    fc            = config.frequency
    SENSING_DEPTH = 2   # depth 2: direct + 1-bounce sufficient for target returns

    agv_indices   = [i for i, t in enumerate(ue_types) if t == "agv"]
    agv_positions = [ue_positions[i] for i in agv_indices]

    print(f"Frequency       : {fc/1e9:.2f} GHz")
    print(f"gNBs            : {len(gnb_positions)}")
    print(f"AGV targets     : {len(agv_positions)}")
    print(f"Bistatic pairs  : {len(BISTATIC_PAIRS)}")
    print(f"Ray depth       : {SENSING_DEPTH}")
    print(f"Range res/bin   : {RANGE_SUM_PER_BIN:.2f} m")
    print(f"Max range sum   : {C/SUBCARRIER_SPACING:.0f} m\n")

    # ── Load scene once ────────────────────────────────────────────────────────
    scene_ref = config.scene
    print(f"Loading scene: {scene_ref} ...", flush=True)
    scene = (load_scene(scene_ref) if "/" in scene_ref or scene_ref.endswith(".xml")
             else load_scene(getattr(scenes, scene_ref)))
    scene.frequency = fc
    print(f"  Scene loaded in {time.time()-t0:.1f}s\n")

    gnb_array = PlanarArray(
        num_rows=config.tx_array.rows, num_cols=config.tx_array.cols,
        vertical_spacing=config.tx_array.spacing,
        horizontal_spacing=config.tx_array.spacing,
        pattern="iso", polarization="V")
    scene.tx_array = gnb_array
    scene.rx_array = gnb_array

    # Add all gNBs as TX; RX offset 1 cm to avoid degenerate zero-delay paths
    RX_OFFSET = 0.01   # metres
    for i, pos in enumerate(gnb_positions):
        scene.add(Transmitter(name=f"gnb_tx_{i}", position=pos))
    for i, pos in enumerate(gnb_positions):
        scene.add(Receiver(name=f"gnb_rx_{i}",
                           position=[pos[0] + RX_OFFSET, pos[1], pos[2]]))

    # ── Single PathSolver call ─────────────────────────────────────────────────
    print(f"PathSolver (max_depth={SENSING_DEPTH}, all {len(gnb_positions)} TX×RX pairs)...", flush=True)
    t1 = time.time()
    paths  = PathSolver()(scene, max_depth=SENSING_DEPTH)
    H_full = cfr_from_paths(paths)
    print(f"  PathSolver done in {time.time()-t1:.1f}s")
    print(f"  CFR shape: {H_full.shape}\n")

    del paths
    gc.collect()

    # ── Per-pair CFAR detection ────────────────────────────────────────────────
    AGV_RCS_M2      = 3.0   # ~3 m² for 1.5m×2m metal AGV at 3.8 GHz
    agv_constraints = [[] for _ in agv_positions]
    pair_results    = []

    print("Per-pair detection:")
    for tx_i, rx_i in BISTATIC_PAIRS:
        h_clut = pair_channel(H_full, tx_i, rx_i)

        detected = 0
        for k, agv_pos in enumerate(agv_positions):
            h_tot   = inject_target(h_clut,
                                    gnb_positions[tx_i], gnb_positions[rx_i],
                                    agv_pos, fc, rcs_m2=AGV_RCS_M2)
            rp_lin  = np.abs(np.fft.ifft(h_tot)) ** 2
            peaks   = cfar_ca_1d(rp_lin)

            R_bi  = (np.linalg.norm(np.array(agv_pos) - np.array(gnb_positions[tx_i]))
                   + np.linalg.norm(np.array(agv_pos) - np.array(gnb_positions[rx_i])))
            R_dir = np.linalg.norm(np.array(gnb_positions[rx_i])
                                 - np.array(gnb_positions[tx_i]))
            bin_th = (R_bi - R_dir) / RANGE_SUM_PER_BIN

            for pk in peaks:
                if abs(pk - bin_th) <= 2.0:
                    agv_constraints[k].append((tx_i, rx_i, R_bi))
                    detected += 1
                    break

        pct = 100 * detected / max(len(agv_positions), 1)
        print(f"  gNB-{tx_i}→gNB-{rx_i}: {detected}/{len(agv_positions)} AGVs  ({pct:.0f}%)")
        pair_results.append({"tx": tx_i, "rx": rx_i,
                              "agv_detections": detected,
                              "total_agvs": len(agv_positions)})

    # ── Localization ───────────────────────────────────────────────────────────
    print("\n=== AGV Localization (5m grid) ===\n")
    print(f"  {'UE':>4}  {'True(x,y)':>18}  {'Est(x,y)':>18}  {'Err(m)':>7}  {'Pairs':>5}")
    print("  " + "─" * 60)

    loc_results = []
    for k, agv_pos in enumerate(agv_positions):
        c = agv_constraints[k]
        if len(c) >= 2:
            est, _ = grid_localize(gnb_positions, c, res=5.0)
            err    = float(np.linalg.norm(np.array(agv_pos[:2]) - np.array(est[:2])))
        else:
            est, err = None, float("nan")

        ts = f"({agv_pos[0]:.1f},{agv_pos[1]:.1f})"
        es = f"({est[0]:.1f},{est[1]:.1f})" if est else "N/A"
        er = f"{err:.1f}" if not np.isnan(err) else "—"
        print(f"  UE-{agv_indices[k]:<3}  {ts:>18}  {es:>18}  {er:>7}  {len(c):>5}")

        loc_results.append({
            "ue_idx":    agv_indices[k],
            "true_pos":  agv_pos,
            "est_pos":   est,
            "error_m":   round(err, 2) if not np.isnan(err) else None,
            "num_pairs": len(c),
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    n_loc  = sum(1 for r in loc_results if r["est_pos"] is not None)
    errors = [r["error_m"] for r in loc_results if r["error_m"] is not None]

    print(f"\n{'='*52}")
    print("ISAC SUMMARY")
    print(f"{'='*52}")
    print(f"  Total runtime        : {time.time()-t0:.1f}s")
    print(f"  AGV targets          : {len(agv_positions)}")
    print(f"  Localized (≥2 pairs) : {n_loc}  ({100*n_loc/max(len(agv_positions),1):.1f}%)")
    if errors:
        print(f"  Mean loc error       : {np.mean(errors):.1f} m")
        print(f"  Median loc error     : {np.median(errors):.1f} m")
        print(f"  Max loc error        : {np.max(errors):.1f} m")
        print(f"  <10 m accuracy       : {sum(e<10 for e in errors)}/{len(errors)}")
        print(f"  <20 m accuracy       : {sum(e<20 for e in errors)}/{len(errors)}")
    print(f"  Range res            : {RANGE_SUM_PER_BIN:.1f} m/bin")

    out = {
        "frequency_ghz":       fc / 1e9,
        "bandwidth_mhz":       round(BW / 1e6, 2),
        "range_sum_per_bin_m": round(RANGE_SUM_PER_BIN, 2),
        "agv_rcs_m2":          AGV_RCS_M2,
        "sensing_max_depth":   SENSING_DEPTH,
        "bistatic_pairs":      [list(p) for p in BISTATIC_PAIRS],
        "pair_results":        pair_results,
        "agv_localization":    loc_results,
        "n_agv_targets":       len(agv_positions),
        "n_localized":         n_loc,
        "localization_pct":    round(100 * n_loc / max(len(agv_positions), 1), 1),
        "mean_error_m":        round(float(np.mean(errors)), 2) if errors else None,
        "median_error_m":      round(float(np.median(errors)), 2) if errors else None,
        "total_runtime_s":     round(time.time() - t0, 1),
    }
    with open("isac_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results → isac_results.json")
    gc.collect()


if __name__ == "__main__":
    main()
