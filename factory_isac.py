"""
Bistatic ISAC sensing — car factory.

Each gNB pair (TX, RX) forms a bistatic link. The OFDM waveform used for
comms is reused for sensing. Static clutter (walls, floor) comes from
Sionna RT ray tracing. AGV point-target returns are injected analytically
using the radar equation. CFAR detects targets; grid search localizes them.

Outputs: isac_results.json
"""

import json
import gc
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
# Only pairs within the same building zone — cross-building pairs suffer heavy
# wall attenuation and are not useful for sensing targets inside a building.
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
    """Extract CFR: [num_rx, rx_ant, num_tx, tx_ant, NUM_ACTIVE_SC] complex64."""
    cfr = paths.cfr(
        frequencies=SC_FREQ_OFFSETS.astype(np.float32),
        out_type="drjit",
    )
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    return torch.from_numpy(H[..., 0, :])   # drop time-step dim


def pair_channel(H_full, tx_i, rx_i):
    """
    Average bistatic channel slice over all antenna elements → [NUM_SC].

    Averaging collapses spatial diversity but preserves delay structure for
    range-profile computation. Angle estimation would require the full
    [rx_ant, tx_ant, SC] tensor — left as future extension.
    """
    return H_full[rx_i, :, tx_i, :, :].mean(dim=(0, 1)).numpy()   # [SC]


def inject_target(h_clutter, tx_pos, rx_pos, tgt_pos, fc, rcs_m2):
    """
    Add a point-target return on top of the clutter channel.

    Radar equation (far-field, single polarisation):
        amplitude  = sqrt(rcs) / (4π · d_tx · d_rx)
        phase      = -2π · (fc + Δf_k) · τ_excess

    τ_excess = τ_bistatic − τ_direct removes the common propagation phase,
    matching Sionna's normalize_delays=True convention so the direct path
    sits at bin 0 and targets appear at positive delay bins.

    Returns complex64 ndarray [NUM_SC].
    """
    tx = np.array(tx_pos, np.float64)
    rx = np.array(rx_pos, np.float64)
    tp = np.array(tgt_pos, np.float64)

    d_tx     = np.linalg.norm(tp - tx)
    d_rx     = np.linalg.norm(tp - rx)
    d_direct = np.linalg.norm(rx - tx)

    tau_excess = (d_tx + d_rx - d_direct) / C          # normalised excess delay

    amp    = np.sqrt(rcs_m2) / (4 * np.pi * d_tx * d_rx)
    freqs  = fc + SC_FREQ_OFFSETS                       # absolute carrier + offset
    h_tgt  = (amp * np.exp(-2j * np.pi * freqs * tau_excess)).astype(np.complex64)

    return h_clutter + h_tgt


def range_profile_db(h_sc):
    """IFFT → delay domain → power in dB [NUM_SC bins]."""
    rp = np.abs(np.fft.ifft(h_sc)) ** 2
    return 10 * np.log10(rp + 1e-30)


def cfar_ca_1d(rp_lin, guard=3, ref=10, pfa=1e-4):
    """
    Cell-averaging CFAR on linear-scale profile.
    Returns list of bin indices where a target is declared.
    """
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
    """d_tx_tgt + d_rx_tgt (metres)."""
    tx = np.array(tx_pos); rx = np.array(rx_pos); tp = np.array(tgt_pos)
    return float(np.linalg.norm(tp - tx) + np.linalg.norm(tp - rx))


def direct_range(tx_pos, rx_pos):
    return float(np.linalg.norm(np.array(rx_pos) - np.array(tx_pos)))


def grid_localize(gnb_positions, range_sum_constraints, res=5.0):
    """
    Least-squares grid-search localization on the factory floor.

    range_sum_constraints : list of (tx_i, rx_i, R_meas) where R_meas is
                            the measured bistatic range SUM (d_tx + d_rx) in m.
    res : grid spacing in metres.

    Returns (est_xyz, rms_residual_m).
    """
    xs = np.arange(0.0, 251.0, res)
    ys = np.arange(0.0, 161.0, res)
    z  = 1.5                                         # AGVs at floor level

    XX, YY = np.meshgrid(xs, ys)                     # [Ny, Nx]
    cost   = np.zeros_like(XX, dtype=np.float64)

    for tx_i, rx_i, R_meas in range_sum_constraints:
        tx = np.array(gnb_positions[tx_i], dtype=np.float64)
        rx = np.array(gnb_positions[rx_i], dtype=np.float64)
        # Vectorised: R_pred[j,i] = d(grid_point, tx) + d(grid_point, rx)
        pts    = np.stack([XX, YY, np.full_like(XX, z)], axis=-1)   # [Ny,Nx,3]
        R_pred = np.linalg.norm(pts - tx, axis=-1) + np.linalg.norm(pts - rx, axis=-1)
        cost  += (R_pred - R_meas) ** 2

    ij   = np.unravel_index(np.argmin(cost), cost.shape)
    est  = [float(xs[ij[1]]), float(ys[ij[0]]), z]
    rms  = float(np.sqrt(cost[ij] / len(range_sum_constraints)))
    return est, rms


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Bistatic ISAC Sensing ===\n")

    config = load_config("config.json")
    with open("config.json") as f:
        raw = json.load(f)

    ue_types      = raw.get("ue_types", [])
    ue_positions  = config.static_receivers
    gnb_positions = config.transmitters
    num_gnbs      = len(gnb_positions)
    fc            = config.frequency

    agv_indices   = [i for i, t in enumerate(ue_types) if t == "agv"]
    agv_positions = [ue_positions[i] for i in agv_indices]

    print(f"Frequency       : {fc/1e9:.2f} GHz")
    print(f"gNBs            : {num_gnbs}")
    print(f"AGV targets     : {len(agv_positions)}")
    print(f"Bistatic pairs  : {len(BISTATIC_PAIRS)}")
    print(f"Range res (bin) : {RANGE_SUM_PER_BIN:.2f} m  (bistatic range sum)")
    print(f"Max range sum   : {C/SUBCARRIER_SPACING:.0f} m\n")

    # ── Scene setup ────────────────────────────────────────────────────────────
    scene_ref = config.scene
    scene = (load_scene(scene_ref) if "/" in scene_ref or scene_ref.endswith(".xml")
             else load_scene(getattr(scenes, scene_ref)))
    scene.frequency = fc

    gnb_array = PlanarArray(
        num_rows=config.tx_array.rows, num_cols=config.tx_array.cols,
        vertical_spacing=config.tx_array.spacing,
        horizontal_spacing=config.tx_array.spacing,
        pattern="iso", polarization="V")
    scene.tx_array = gnb_array
    scene.rx_array = gnb_array   # gNBs act as RX for sensing

    for i, pos in enumerate(gnb_positions):
        scene.add(Transmitter(name=f"gnb_tx_{i}", position=pos))
    for i, pos in enumerate(gnb_positions):
        scene.add(Receiver(name=f"gnb_rx_{i}", position=pos))

    # ── Clutter channel via ray tracing ────────────────────────────────────────
    print("PathSolver: bistatic clutter channel...")
    paths  = PathSolver()(scene, max_depth=config.max_depth)
    H_full = cfr_from_paths(paths)
    # shape: [num_gnbs, rx_ant, num_gnbs, tx_ant, NUM_SC]
    print(f"Sensing CFR     : {tuple(H_full.shape)}\n")

    del paths
    gc.collect()

    # ── Per-pair bistatic processing ───────────────────────────────────────────
    # For each (TX, RX) gNB pair and each AGV:
    #   1. Extract clutter channel from H_full
    #   2. Inject synthetic AGV target return (radar equation)
    #   3. IFFT → range profile → CFAR
    #   4. Check if a CFAR peak aligns with the theoretical bistatic range sum
    #
    # AGV RCS: ~3 m² at 3.8 GHz for a 1.5m×2m metal body (conservative)
    AGV_RCS_M2 = 3.0

    # agv_constraints[k] accumulates (tx_i, rx_i, R_meas) for AGV k
    agv_constraints = [[] for _ in agv_positions]

    print("Processing bistatic pairs:")
    pair_results = []

    for tx_i, rx_i in BISTATIC_PAIRS:
        h_clutter = pair_channel(H_full, tx_i, rx_i)   # [NUM_SC] complex64

        detected_for_pair = 0
        for k, agv_pos in enumerate(agv_positions):
            h_total = inject_target(h_clutter, gnb_positions[tx_i], gnb_positions[rx_i],
                                    agv_pos, fc, rcs_m2=AGV_RCS_M2)

            rp_lin  = np.abs(np.fft.ifft(h_total)) ** 2
            peaks   = cfar_ca_1d(rp_lin)

            # Theoretical excess range sum = bistatic sum − direct distance
            R_bistatic = bistatic_range_sum(gnb_positions[tx_i], gnb_positions[rx_i], agv_pos)
            R_direct   = direct_range(gnb_positions[tx_i], gnb_positions[rx_i])
            R_excess   = R_bistatic - R_direct
            bin_theory = R_excess / RANGE_SUM_PER_BIN

            for pk in peaks:
                if abs(pk - bin_theory) <= 2.0:    # within ±2 range bins
                    agv_constraints[k].append((tx_i, rx_i, R_bistatic))
                    detected_for_pair += 1
                    break

        pair_results.append({
            "tx": tx_i, "rx": rx_i,
            "agv_detections": detected_for_pair,
            "total_agvs": len(agv_positions),
        })
        pct = 100 * detected_for_pair / max(len(agv_positions), 1)
        print(f"  gNB-{tx_i}→gNB-{rx_i}: {detected_for_pair}/{len(agv_positions)} AGVs  ({pct:.0f}%)")

    # ── Localization ───────────────────────────────────────────────────────────
    print("\n=== AGV Localization (grid search, 5m resolution) ===\n")
    w = 88
    print(f"  {'UE':>4}  {'True pos (x, y)':>20}  {'Est pos (x, y)':>20}  {'Err(m)':>7}  {'Pairs':>5}")
    print("  " + "─" * w)

    loc_results = []
    for k, agv_pos in enumerate(agv_positions):
        constraints = agv_constraints[k]
        if len(constraints) >= 2:
            est, _ = grid_localize(gnb_positions, constraints, res=5.0)
            err    = float(np.linalg.norm(
                np.array(agv_pos[:2]) - np.array(est[:2])
            ))
        else:
            est = None
            err = float("nan")

        true_s = f"({agv_pos[0]:.1f}, {agv_pos[1]:.1f})"
        est_s  = f"({est[0]:.1f}, {est[1]:.1f})" if est else "N/A"
        err_s  = f"{err:.1f}" if not np.isnan(err) else "—"
        print(f"  UE-{agv_indices[k]:<3}  {true_s:>20}  {est_s:>20}  {err_s:>7}  {len(constraints):>5}")

        loc_results.append({
            "ue_idx":      agv_indices[k],
            "true_pos":    agv_pos,
            "est_pos":     est,
            "error_m":     round(err, 2) if not np.isnan(err) else None,
            "num_pairs":   len(constraints),
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    n_loc  = sum(1 for r in loc_results if r["est_pos"] is not None)
    errors = [r["error_m"] for r in loc_results if r["error_m"] is not None]

    print(f"\n{'='*50}")
    print(f"ISAC SUMMARY")
    print(f"{'='*50}")
    print(f"  AGV targets         : {len(agv_positions)}")
    print(f"  Localized (≥2 pairs): {n_loc}  ({100*n_loc/max(len(agv_positions),1):.1f}%)")
    if errors:
        print(f"  Mean loc error      : {np.mean(errors):.1f} m")
        print(f"  Median loc error    : {np.median(errors):.1f} m")
        print(f"  Max loc error       : {np.max(errors):.1f} m")
        print(f"  <10 m accuracy      : {sum(e<10 for e in errors)}/{len(errors)}")
        print(f"  <20 m accuracy      : {sum(e<20 for e in errors)}/{len(errors)}")
    print(f"\n  Note: range resolution = {RANGE_SUM_PER_BIN:.1f} m/bin at 18.36 MHz BW")
    print(f"  Note: grid search at 5m resolution; refine with gradient descent for <5m")

    out = {
        "frequency_ghz":         fc / 1e9,
        "bandwidth_mhz":         round(BW / 1e6, 2),
        "range_sum_per_bin_m":   round(RANGE_SUM_PER_BIN, 2),
        "max_bistatic_range_m":  round(C / SUBCARRIER_SPACING, 1),
        "agv_rcs_m2":            AGV_RCS_M2,
        "num_bistatic_pairs":    len(BISTATIC_PAIRS),
        "bistatic_pairs":        [list(p) for p in BISTATIC_PAIRS],
        "pair_results":          pair_results,
        "agv_localization":      loc_results,
        "n_agv_targets":         len(agv_positions),
        "n_localized":           n_loc,
        "localization_pct":      round(100 * n_loc / max(len(agv_positions), 1), 1),
        "mean_error_m":          round(float(np.mean(errors)), 2) if errors else None,
        "median_error_m":        round(float(np.median(errors)), 2) if errors else None,
    }
    with open("isac_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results → isac_results.json")

    gc.collect()


if __name__ == "__main__":
    main()
