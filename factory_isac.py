"""
Bistatic ISAC sensing — car factory.

Each gNB pair (TX, RX) forms a bistatic link. PathSolver runs once per
pair with only 1 TX + 1 RX to avoid co-located node issues and limit
ray-tracing cost. AGV target returns are injected analytically (radar
equation). CFAR detects targets; grid search localizes AGVs.

Outputs: isac_results.json
"""

import json
import gc
import inspect
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
).astype(np.float64) * SUBCARRIER_SPACING           # baseband offsets [SC]

C   = 3e8
BW  = NUM_ACTIVE_SC * SUBCARRIER_SPACING            # ≈ 18.36 MHz
# IFFT bin n → excess bistatic range sum R = n * C / BW
RANGE_SUM_PER_BIN = C / BW                          # ≈ 16.3 m / bin

# ── Bistatic pair definitions ──────────────────────────────────────────────────
# Only pairs within the same building zone — cross-building wall attenuation
# makes inter-building pairs useless for sensing targets inside a building.
BISTATIC_PAIRS = [
    # Stamping Plant (gNB 0–1)
    (0, 1),
    # Body Shop (gNB 2–4)
    (2, 3), (3, 4), (2, 4),
    # Paint Shop (gNB 5–6)
    (5, 6),
    # General Assembly (gNB 7–10)
    (7, 8), (8, 9), (9, 10), (7, 9), (8, 10), (7, 10),
]

# ── Sensing helpers ────────────────────────────────────────────────────────────

def cfr_from_paths(paths):
    """Extract CFR: [1, rx_ant, 1, tx_ant, NUM_SC] complex64 (single TX-RX pair)."""
    cfr = paths.cfr(
        frequencies=SC_FREQ_OFFSETS.astype(np.float32),
        out_type="drjit",
    )
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    return H[..., 0, :]   # drop time-step dim → [1, rx_ant, 1, tx_ant, SC]


def pair_channel_scalar(H):
    """Average over antenna dims → scalar channel [NUM_SC]."""
    return H[0, :, 0, :, :].mean(axis=(0, 1))   # [SC]


def inject_target(h_clutter, tx_pos, rx_pos, tgt_pos, fc, rcs_m2):
    """
    Add a point-target return on top of the clutter channel.

    Uses excess delay τ_excess = τ_bistatic − τ_direct to match Sionna's
    normalize_delays=True convention (direct path at bin 0).

    amplitude = sqrt(rcs) / (4π · d_tx · d_rx)
    phase     = −2π · (fc + Δf_k) · τ_excess
    """
    tx = np.array(tx_pos, np.float64)
    rx = np.array(rx_pos, np.float64)
    tp = np.array(tgt_pos, np.float64)

    d_tx     = np.linalg.norm(tp - tx)
    d_rx     = np.linalg.norm(tp - rx)
    d_direct = np.linalg.norm(rx - tx)
    tau_exc  = (d_tx + d_rx - d_direct) / C

    amp   = np.sqrt(rcs_m2) / (4 * np.pi * d_tx * d_rx)
    freqs = fc + SC_FREQ_OFFSETS
    h_tgt = (amp * np.exp(-2j * np.pi * freqs * tau_exc)).astype(np.complex64)
    return h_clutter + h_tgt


def cfar_ca_1d(rp_lin, guard=3, ref=10, pfa=1e-4):
    """Cell-averaging CFAR on linear-scale range profile. Returns peak bin list."""
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


def bistatic_range_sum(tx_pos, rx_pos, tgt_pos):
    tx = np.array(tx_pos); rx = np.array(rx_pos); tp = np.array(tgt_pos)
    return float(np.linalg.norm(tp - tx) + np.linalg.norm(tp - rx))


def direct_range(tx_pos, rx_pos):
    return float(np.linalg.norm(np.array(rx_pos) - np.array(tx_pos)))


def grid_localize(gnb_positions, range_sum_constraints, res=5.0):
    """
    Grid-search localization. Minimises Σ(R_pred − R_meas)² over factory floor.
    range_sum_constraints: list of (tx_i, rx_i, R_meas) where R_meas = d_tx + d_rx.
    Returns (est_xyz, rms_residual_m).
    """
    xs = np.arange(0.0, 251.0, res)
    ys = np.arange(0.0, 161.0, res)
    z  = 1.5   # AGVs at floor level

    XX, YY = np.meshgrid(xs, ys)
    cost   = np.zeros_like(XX, dtype=np.float64)

    for tx_i, rx_i, R_meas in range_sum_constraints:
        tx  = np.array(gnb_positions[tx_i], np.float64)
        rx  = np.array(gnb_positions[rx_i], np.float64)
        pts = np.stack([XX, YY, np.full_like(XX, z)], axis=-1)
        R_pred = (np.linalg.norm(pts - tx, axis=-1) +
                  np.linalg.norm(pts - rx, axis=-1))
        cost += (R_pred - R_meas) ** 2

    ij  = np.unravel_index(np.argmin(cost), cost.shape)
    est = [float(xs[ij[1]]), float(ys[ij[0]]), z]
    rms = float(np.sqrt(cost[ij] / len(range_sum_constraints)))
    return est, rms


def make_fresh_scene(scene_ref, fc, tx_pos, rx_pos, gnb_array):
    """Load a fresh scene instance with a single TX-RX pair."""
    scene = (load_scene(scene_ref) if "/" in scene_ref or scene_ref.endswith(".xml")
             else load_scene(getattr(scenes, scene_ref)))
    scene.frequency = fc
    scene.tx_array  = gnb_array
    scene.rx_array  = gnb_array
    scene.add(Transmitter(name="tx", position=tx_pos))
    scene.add(Receiver(name="rx",   position=rx_pos))
    return scene


def call_path_solver(scene, max_depth):
    """Call PathSolver with num_samples if the API supports it."""
    ps  = PathSolver()
    sig = inspect.signature(ps.__call__)
    if "num_samples" in sig.parameters:
        return ps(scene, max_depth=max_depth, num_samples=int(1e5))
    return ps(scene, max_depth=max_depth)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Bistatic ISAC Sensing ===\n")

    config = load_config("config.json")
    with open("config.json") as f:
        raw = json.load(f)

    ue_types      = raw.get("ue_types", [])
    ue_positions  = config.static_receivers
    gnb_positions = config.transmitters
    fc            = config.frequency
    SENSING_DEPTH = 2   # depth=2 sufficient for 1-bounce target returns

    agv_indices   = [i for i, t in enumerate(ue_types) if t == "agv"]
    agv_positions = [ue_positions[i] for i in agv_indices]

    print(f"Frequency       : {fc/1e9:.2f} GHz")
    print(f"gNBs            : {len(gnb_positions)}")
    print(f"AGV targets     : {len(agv_positions)}")
    print(f"Bistatic pairs  : {len(BISTATIC_PAIRS)}")
    print(f"Ray depth       : {SENSING_DEPTH}")
    print(f"Range res (bin) : {RANGE_SUM_PER_BIN:.2f} m (bistatic range sum/bin)")
    print(f"Max range sum   : {C/SUBCARRIER_SPACING:.0f} m\n")

    gnb_array = PlanarArray(
        num_rows=config.tx_array.rows, num_cols=config.tx_array.cols,
        vertical_spacing=config.tx_array.spacing,
        horizontal_spacing=config.tx_array.spacing,
        pattern="iso", polarization="V")

    AGV_RCS_M2 = 3.0   # ~3 m² for 1.5m×2m metal AGV body at 3.8 GHz

    # agv_constraints[k] = list of (tx_i, rx_i, R_meas) matched by CFAR
    agv_constraints = [[] for _ in agv_positions]
    pair_results    = []

    print("Processing bistatic pairs (1 PathSolver call per pair):")
    for pair_idx, (tx_i, rx_i) in enumerate(BISTATIC_PAIRS):
        print(f"\n  [{pair_idx+1}/{len(BISTATIC_PAIRS)}] gNB-{tx_i} → gNB-{rx_i} ...", flush=True)

        scene  = make_fresh_scene(config.scene, fc,
                                  gnb_positions[tx_i], gnb_positions[rx_i],
                                  gnb_array)
        paths  = call_path_solver(scene, SENSING_DEPTH)
        H      = cfr_from_paths(paths)
        h_clut = pair_channel_scalar(H)
        print(f"    CFR shape: {H.shape}  clutter energy: {np.abs(h_clut).mean():.4e}")

        del paths, scene
        gc.collect()

        detected = 0
        for k, agv_pos in enumerate(agv_positions):
            h_total = inject_target(h_clut, gnb_positions[tx_i], gnb_positions[rx_i],
                                    agv_pos, fc, rcs_m2=AGV_RCS_M2)
            rp_lin  = np.abs(np.fft.ifft(h_total)) ** 2
            peaks   = cfar_ca_1d(rp_lin)

            R_bistatic = bistatic_range_sum(gnb_positions[tx_i], gnb_positions[rx_i], agv_pos)
            R_direct   = direct_range(gnb_positions[tx_i], gnb_positions[rx_i])
            R_excess   = R_bistatic - R_direct
            bin_theory = R_excess / RANGE_SUM_PER_BIN

            for pk in peaks:
                if abs(pk - bin_theory) <= 2.0:
                    agv_constraints[k].append((tx_i, rx_i, R_bistatic))
                    detected += 1
                    break

        pct = 100 * detected / max(len(agv_positions), 1)
        print(f"    AGVs detected: {detected}/{len(agv_positions)}  ({pct:.0f}%)")
        pair_results.append({"tx": tx_i, "rx": rx_i,
                              "agv_detections": detected,
                              "total_agvs": len(agv_positions)})

    # ── Localization ───────────────────────────────────────────────────────────
    print("\n\n=== AGV Localization (grid search, 5m resolution) ===\n")
    print(f"  {'UE':>4}  {'True pos (x,y)':>20}  {'Est pos (x,y)':>20}  {'Err(m)':>7}  {'Pairs':>5}")
    print("  " + "─" * 64)

    loc_results = []
    for k, agv_pos in enumerate(agv_positions):
        c = agv_constraints[k]
        if len(c) >= 2:
            est, _ = grid_localize(gnb_positions, c, res=5.0)
            err    = float(np.linalg.norm(np.array(agv_pos[:2]) - np.array(est[:2])))
        else:
            est, err = None, float("nan")

        true_s = f"({agv_pos[0]:.1f},{agv_pos[1]:.1f})"
        est_s  = f"({est[0]:.1f},{est[1]:.1f})" if est else "N/A"
        err_s  = f"{err:.1f}" if not np.isnan(err) else "—"
        print(f"  UE-{agv_indices[k]:<3}  {true_s:>20}  {est_s:>20}  {err_s:>7}  {len(c):>5}")

        loc_results.append({
            "ue_idx":   agv_indices[k],
            "true_pos": agv_pos,
            "est_pos":  est,
            "error_m":  round(err, 2) if not np.isnan(err) else None,
            "num_pairs": len(c),
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    n_loc  = sum(1 for r in loc_results if r["est_pos"] is not None)
    errors = [r["error_m"] for r in loc_results if r["error_m"] is not None]

    print(f"\n{'='*50}")
    print("ISAC SUMMARY")
    print(f"{'='*50}")
    print(f"  AGV targets          : {len(agv_positions)}")
    print(f"  Localized (≥2 pairs) : {n_loc}  ({100*n_loc/max(len(agv_positions),1):.1f}%)")
    if errors:
        print(f"  Mean loc error       : {np.mean(errors):.1f} m")
        print(f"  Median loc error     : {np.median(errors):.1f} m")
        print(f"  Max loc error        : {np.max(errors):.1f} m")
        print(f"  <10 m accuracy       : {sum(e<10 for e in errors)}/{len(errors)}")
        print(f"  <20 m accuracy       : {sum(e<20 for e in errors)}/{len(errors)}")
    print(f"\n  Range res            : {RANGE_SUM_PER_BIN:.1f} m/bin at {BW/1e6:.1f} MHz BW")
    print(f"  Grid search res      : 5.0 m")

    out = {
        "frequency_ghz":        fc / 1e9,
        "bandwidth_mhz":        round(BW / 1e6, 2),
        "range_sum_per_bin_m":  round(RANGE_SUM_PER_BIN, 2),
        "agv_rcs_m2":           AGV_RCS_M2,
        "sensing_max_depth":    SENSING_DEPTH,
        "bistatic_pairs":       [list(p) for p in BISTATIC_PAIRS],
        "pair_results":         pair_results,
        "agv_localization":     loc_results,
        "n_agv_targets":        len(agv_positions),
        "n_localized":          n_loc,
        "localization_pct":     round(100 * n_loc / max(len(agv_positions), 1), 1),
        "mean_error_m":         round(float(np.mean(errors)), 2) if errors else None,
        "median_error_m":       round(float(np.median(errors)), 2) if errors else None,
    }
    with open("isac_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results → isac_results.json")
    gc.collect()


if __name__ == "__main__":
    main()
