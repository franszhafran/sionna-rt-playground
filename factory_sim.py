import os
import json
import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver
import sionna.rt.scene as scenes
import gc

from config_schema import load_config

# ── 5G NR OFDM Parameters (numerology μ=1, 30 kHz SCS, 20 MHz channel) ───────
# Reference: 3GPP TS 38.101-1 Table 5.3.2-1
SUBCARRIER_SPACING = 30e3           # Hz — Δf
NUM_RBS            = 51             # Resource blocks for 20 MHz / 30 kHz SCS
SUBCARRIERS_PER_RB = 12             # fixed in NR
NUM_ACTIVE_SC      = NUM_RBS * SUBCARRIERS_PER_RB        # 612 active subcarriers
# CP efficiency: 14 useful OFDM symbols occupy 14/Δf = 466.67 µs of a 500 µs slot
CP_EFFICIENCY = 14 * (1.0 / SUBCARRIER_SPACING) / 0.5e-3   # ≈ 0.9333
USEFUL_BW     = NUM_ACTIVE_SC * SUBCARRIER_SPACING          # ≈ 18.36 MHz

# Baseband subcarrier frequency offsets (DC excluded, symmetric)
_half = NUM_ACTIVE_SC // 2
SC_FREQUENCIES = np.concatenate(
    [np.arange(-_half, 0), np.arange(1, _half + 1)]
).astype(np.float32) * SUBCARRIER_SPACING   # shape [NUM_ACTIVE_SC]

# ── QoS requirements per UE type ──────────────────────────────────────────────
QOS = {
    "agv":           {"latency_ms": 10.0,  "throughput_mbps":  5.0},
    "robotic_arm":   {"latency_ms":  5.0,  "throughput_mbps":  1.0},
    "vision_camera": {"latency_ms": 50.0,  "throughput_mbps": 50.0},
    "safety_sensor": {"latency_ms":  2.0,  "throughput_mbps":  0.1},
    "worker_tablet": {"latency_ms": 100.0, "throughput_mbps": 10.0},
}


# ── OFDM channel ──────────────────────────────────────────────────────────────

def compute_ofdm_channel(paths):
    """Convert ray-traced paths to per-subcarrier frequency-domain channel.

    Uses Sionna's paths.cfr() which evaluates
        H[k] = Σ_l a_l · exp(−j2π f_k τ_l)
    at each active subcarrier frequency f_k, with timing-aligned delays
    (normalize_delays=True removes the common propagation phase, equivalent
    to receiver synchronisation).

    Returns: complex64 tensor [num_rx, num_rx_ant, num_tx, num_tx_ant, NUM_ACTIVE_SC]
    """
    cfr = paths.cfr(frequencies=SC_FREQUENCIES, out_type="drjit")
    H = (np.array(cfr[0]) + 1j * np.array(cfr[1])).astype(np.complex64)
    # cfr shape: (num_rx, num_rx_ant, num_tx, num_tx_ant, num_time_steps=1, NUM_ACTIVE_SC)
    return torch.from_numpy(H[..., 0, :])   # drop time dim


# ── OFDM beamforming ──────────────────────────────────────────────────────────

def compute_mmse_ofdm(h_ofdm, tx_idx, noise_var=1e-8):
    """Per-RB MMSE beamforming with per-subcarrier SINR evaluation.

    Beamforming weights are computed once per RB (average H over 12 SCs in
    the RB), then applied to each individual subcarrier's H for an accurate
    frequency-selective SINR.  This mirrors real 5G NR CSI-RS precoding.

    h_ofdm : [num_rx, num_rx_ant, num_tx, num_tx_ant, NUM_ACTIVE_SC]
    Returns : sinr_db  [num_rx, NUM_ACTIVE_SC]
    """
    num_rx = h_ofdm.shape[0]

    # H for this gNB, single-element RX antenna: [num_rx, num_tx_ant, NUM_ACTIVE_SC]
    H_full = h_ofdm[:, 0, tx_idx, :, :]

    # Permute to [SC, num_rx, num_tx_ant] for batched ops
    H_sc = H_full.permute(2, 0, 1)                              # [SC, rx, tx_ant]

    # Average channel per RB → [NUM_RBS, rx, tx_ant]
    H_rb = H_sc.reshape(NUM_RBS, SUBCARRIERS_PER_RB, num_rx, -1).mean(dim=1)

    # MMSE precoder per RB: W = H^H (H H^H + σ²I)^{-1}  [NUM_RBS, tx_ant, rx]
    H_h     = H_rb.mH                                           # [RB, tx_ant, rx]
    HHH     = torch.bmm(H_rb, H_h)                              # [RB, rx, rx]
    reg     = HHH + noise_var * torch.eye(num_rx, dtype=H_rb.dtype).unsqueeze(0)
    try:
        inv_reg = torch.linalg.inv(reg)
    except Exception:
        inv_reg = torch.linalg.pinv(reg)
    W = torch.bmm(H_h, inv_reg)                                 # [RB, tx_ant, rx]
    W = W / (W.norm(dim=1, keepdim=True) + 1e-10)               # normalise per-UE columns

    # Expand RB weights to individual subcarriers
    W_sc = W.repeat_interleave(SUBCARRIERS_PER_RB, dim=0)       # [SC, tx_ant, rx]

    # Effective channel per subcarrier: Hw = H_sc @ W_sc  [SC, rx, rx]
    Hw = torch.bmm(H_sc, W_sc)

    sig_pow  = torch.diagonal(Hw, dim1=1, dim2=2).abs() ** 2    # [SC, rx]  signal
    interf   = (Hw.abs() ** 2).sum(dim=2) - sig_pow             # [SC, rx]  interference
    sinr_lin = sig_pow / (interf + noise_var)
    sinr_db  = 10 * torch.log10(sinr_lin + 1e-10)

    return sinr_db.T    # [num_rx, NUM_ACTIVE_SC]


def compute_mrt_ofdm(h_ofdm, tx_idx, rx_idx):
    """Per-subcarrier MRT for a single UE.

    Returns received signal power in dB per subcarrier [NUM_ACTIVE_SC].
    """
    h = h_ofdm[rx_idx, 0, tx_idx, :, :]         # [tx_ant, NUM_ACTIVE_SC]
    w = torch.conj(h) / (h.norm(dim=0, keepdim=True) + 1e-10)
    return 10 * torch.log10((h * w).sum(dim=0).abs() ** 2 + 1e-10)


# ── Flat-fading beamforming (statistical channel fallback) ────────────────────

def compute_mmse_beamforming(h_eff, tx_idx, noise_var=1e-8):
    num_rx = h_eff.shape[0]
    H = h_eff[:, 0, tx_idx, :]
    H_hermit  = H.conj().T
    HH_hermit = torch.matmul(H, H_hermit)
    regularized = HH_hermit + noise_var * torch.eye(num_rx, dtype=H.dtype)
    try:
        inv_reg = torch.linalg.inv(regularized)
    except Exception:
        inv_reg = torch.linalg.pinv(regularized)
    W_mmse = torch.matmul(H_hermit, inv_reg)
    for ue_idx in range(num_rx):
        w_norm = torch.norm(W_mmse[:, ue_idx])
        if w_norm > 1e-10:
            W_mmse[:, ue_idx] /= w_norm
    powers_db = []
    for ue_idx in range(num_rx):
        h_ue = h_eff[ue_idx, 0, tx_idx, :]
        w_ue = W_mmse[:, ue_idx]
        signal = torch.abs(torch.sum(h_ue * w_ue))
        interference = sum(
            torch.abs(torch.sum(h_ue * W_mmse[:, j])) ** 2
            for j in range(num_rx) if j != ue_idx
        )
        sinr = signal ** 2 / (interference + noise_var)
        powers_db.append(10 * torch.log10(sinr + 1e-10))
    return powers_db, W_mmse


def compute_mrt_beamforming(h_eff, tx_idx, rx_idx):
    h_pair = h_eff[rx_idx, :, tx_idx, :]
    w = torch.conj(h_pair[0, :])
    w /= torch.norm(w) + 1e-10
    received = torch.abs(torch.sum(h_pair[0, :] * w))
    return 20 * torch.log10(received + 1e-10), w


def generate_statistical_channel(num_tx, num_rx, num_tx_ant, num_rx_ant,
                                  tx_positions, rx_positions, frequency):
    h_stat = torch.zeros(num_rx, num_rx_ant, num_tx, num_tx_ant, dtype=torch.complex64)
    for tx_idx in range(num_tx):
        for rx_idx in range(num_rx):
            d = max(np.linalg.norm(
                np.array(tx_positions[tx_idx]) - np.array(rx_positions[rx_idx])), 1.0)
            pl_db  = 31.84 + 21.50 * np.log10(d) + 19.00 * np.log10(frequency / 1e9)
            pl_lin = 10 ** (-pl_db / 20)
            fading = torch.complex(torch.randn(num_rx_ant, num_tx_ant),
                                   torch.randn(num_rx_ant, num_tx_ant)) / np.sqrt(2)
            h_stat[rx_idx, :, tx_idx, :] = pl_lin * fading
    return h_stat


# ── Layout printer ────────────────────────────────────────────────────────────

def print_factory_layout(tx_positions, rx_positions):
    all_pos = list(tx_positions) + list(rx_positions)
    x_max = max(p[0] for p in all_pos)
    y_max = max(p[1] for p in all_pos)
    cell  = max(1, int(max(x_max / 60, y_max / 36)))
    W = int(x_max / cell) + 2
    H = int(y_max / cell) + 2
    grid = [['.' for _ in range(W)] for _ in range(H)]
    for pos in tx_positions:
        c, r = int(round(pos[0] / cell)), int(round(pos[1] / cell))
        if 0 <= r < H and 0 <= c < W: grid[r][c] = 'G'
    for pos in rx_positions:
        c, r = int(round(pos[0] / cell)), int(round(pos[1] / cell))
        if 0 <= r < H and 0 <= c < W and grid[r][c] != 'G': grid[r][c] = 'U'
    print("\n" + "=" * 70)
    print(f"FACTORY FLOOR LAYOUT  (each cell ≈ {cell}m)  G=gNB  U=UE")
    print("=" * 70)
    for row_y in range(H - 1, -1, -1):
        print(f"{row_y*cell:4d}|{''.join(grid[row_y])}|")
    print("     " + "-" * W + "\n     x-axis (metres)")
    print("\n--- gNB Positions ---")
    print(f"  {'ID':<8} {'x':>7} {'y':>7} {'z':>6}")
    for i, pos in enumerate(tx_positions):
        print(f"  gNB-{i:<4} {pos[0]:>7.1f} {pos[1]:>7.1f} {pos[2]:>6.1f}")
    print("\n--- Static UE Positions ---")
    print(f"  {'ID':<10} {'x':>7} {'y':>7} {'z':>6}")
    for i, pos in enumerate(rx_positions):
        print(f"  UE-{i:<7} {pos[0]:>7.1f} {pos[1]:>7.1f} {pos[2]:>6.1f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading configuration...")
    config = load_config("config.json")
    with open("config.json") as f:
        raw = json.load(f)
    ue_types = raw.get("ue_types", [])
    print("Configuration validated.\n")

    bf_method       = config.beamforming_method
    noise_var       = config.noise_variance
    use_statistical = getattr(config, 'use_statistical_channel', False)

    print(f"Scene          : {config.scene}")
    print(f"Frequency      : {config.frequency/1e9:.2f} GHz")
    print(f"Beamforming    : {bf_method}")
    if not use_statistical:
        print(f"Channel model  : OFDM Ray Tracing")
        print(f"OFDM           : {NUM_ACTIVE_SC} subcarriers  "
              f"Δf={int(SUBCARRIER_SPACING/1e3)} kHz  "
              f"{NUM_RBS} RBs  BW≈{USEFUL_BW/1e6:.2f} MHz  "
              f"CP eff={CP_EFFICIENCY:.4f}")
    else:
        print(f"Channel model  : Statistical 3GPP InF-SH (flat-fading, no OFDM)")

    scene_ref = config.scene
    scene = (load_scene(scene_ref) if "/" in scene_ref or scene_ref.endswith(".xml")
             else load_scene(getattr(scenes, scene_ref)))

    num_tx_ant = config.tx_array.rows * config.tx_array.cols
    num_rx_ant = config.rx_array.rows * config.rx_array.cols

    scene.tx_array = PlanarArray(
        num_rows=config.tx_array.rows, num_cols=config.tx_array.cols,
        vertical_spacing=config.tx_array.spacing,
        horizontal_spacing=config.tx_array.spacing,
        pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(
        num_rows=config.rx_array.rows, num_cols=config.rx_array.cols,
        vertical_spacing=config.rx_array.spacing,
        horizontal_spacing=config.rx_array.spacing,
        pattern="iso", polarization="V")

    tx_positions = config.transmitters
    rx_positions = config.static_receivers
    num_tx = len(tx_positions)
    num_rx = len(rx_positions)

    for i, pos in enumerate(tx_positions): scene.add(Transmitter(name=f"gnb-{i}", position=pos))
    for i, pos in enumerate(rx_positions): scene.add(Receiver(name=f"ue-{i}",  position=pos))
    scene.frequency = config.frequency

    print_factory_layout(tx_positions, rx_positions)

    print("\n\n=== Computing Channels ===")

    use_ofdm = False
    if use_statistical:
        h_eff = generate_statistical_channel(
            num_tx, num_rx, num_tx_ant, num_rx_ant,
            tx_positions, rx_positions, config.frequency)
    else:
        path_solver = PathSolver()
        paths  = path_solver(scene, max_depth=config.max_depth)
        print(f"Computing OFDM CFR for {NUM_ACTIVE_SC} subcarriers ({NUM_RBS} RBs × {SUBCARRIERS_PER_RB} SC/RB)...")
        h_ofdm = compute_ofdm_channel(paths)
        print(f"CFR tensor shape: {tuple(h_ofdm.shape)}")
        use_ofdm = True

    print(f"Computing {bf_method} beamforming...")

    if use_ofdm:
        sinr_db_cube = np.full((num_rx, num_tx, NUM_ACTIVE_SC), -100.0, dtype=np.float32)

        if bf_method.upper() == 'MMSE':
            for tx_idx in range(num_tx):
                print(f"  MMSE gNB-{tx_idx}...", end=" ", flush=True)
                sinr_db_cube[:, tx_idx, :] = compute_mmse_ofdm(h_ofdm, tx_idx, noise_var).numpy()
                print("done")
        else:
            for tx_idx in range(num_tx):
                for rx_idx in range(num_rx):
                    sinr_db_cube[rx_idx, tx_idx, :] = \
                        compute_mrt_ofdm(h_ofdm, tx_idx, rx_idx).numpy()

        # Throughput: Δf × Σ_k log₂(1 + SINRₖ) × CP_efficiency  [Mbps]
        tput_matrix = (
            SUBCARRIER_SPACING
            * np.log2(1.0 + 10.0 ** (sinr_db_cube / 10.0))
            * CP_EFFICIENCY
        ).sum(axis=2) / 1e6                              # [num_rx, num_tx]

        best_gnb        = np.argmax(tput_matrix, axis=1)
        throughput_mbps = tput_matrix[np.arange(num_rx), best_gnb]
        # Average SINR across subcarriers per UE (for display)
        best_sinr_db    = sinr_db_cube[np.arange(num_rx), best_gnb, :].mean(axis=1)

    else:
        # Flat-fading statistical channel path (unchanged)
        sinr_db_matrix = np.zeros((num_rx, num_tx))
        if bf_method.upper() == 'MMSE':
            for tx_idx in range(num_tx):
                powers_db, _ = compute_mmse_beamforming(h_eff, tx_idx, noise_var)
                for rx_idx in range(num_rx):
                    sinr_db_matrix[rx_idx, tx_idx] = powers_db[rx_idx].item()
        else:
            for tx_idx in range(num_tx):
                for rx_idx in range(num_rx):
                    power_db, _ = compute_mrt_beamforming(h_eff, tx_idx, rx_idx)
                    sinr_db_matrix[rx_idx, tx_idx] = power_db.item()

        best_gnb        = np.argmax(sinr_db_matrix, axis=1)
        best_sinr_db    = sinr_db_matrix[np.arange(num_rx), best_gnb]
        throughput_mbps = 20e6 * np.log2(1 + 10 ** (best_sinr_db / 10)) / 1e6

    # ── Latency ───────────────────────────────────────────────────────────────
    slot_ms    = 0.5   # 5G NR 30 kHz SCS slot duration
    latency_ms = np.array([
        np.linalg.norm(np.array(rx_positions[i]) - np.array(tx_positions[best_gnb[i]])) / 3e8 * 1000
        + slot_ms
        for i in range(num_rx)
    ])

    # ── QoS SLA check ─────────────────────────────────────────────────────────
    sla_pass        = np.ones(num_rx, dtype=bool)
    sla_fail_reason = [""] * num_rx
    for i in range(num_rx):
        ue_type = ue_types[i] if i < len(ue_types) else None
        if ue_type and ue_type in QOS:
            req       = QOS[ue_type]
            lat_fail  = latency_ms[i]    > req["latency_ms"]
            tput_fail = throughput_mbps[i] < req["throughput_mbps"]
            if lat_fail or tput_fail:
                sla_pass[i] = False
                reasons = []
                if lat_fail:  reasons.append(f"lat>{req['latency_ms']}ms")
                if tput_fail: reasons.append(f"tput<{req['throughput_mbps']}Mbps")
                sla_fail_reason[i] = ",".join(reasons)

    # ── Output tables ─────────────────────────────────────────────────────────
    W = 105
    sinr_label = "AvgSINR(dB)" if use_ofdm else "SINR(dB)"

    print("\n" + "=" * W)
    print("PER-UE PERFORMANCE  (best serving gNB)")
    print("=" * W)
    print(f"{'UE':<8} {'Type':<16} {'Best gNB':<9} {sinr_label:>12} {'Tput(Mbps)':>11} {'Lat(ms)':>9}  SLA")
    print("-" * W)
    for i in range(num_rx):
        ue_type = ue_types[i] if i < len(ue_types) else "unknown"
        sla     = "PASS" if sla_pass[i] else f"FAIL ({sla_fail_reason[i]})"
        print(f"UE-{i:<5} {ue_type:<16} gNB-{best_gnb[i]:<5} "
              f"{best_sinr_db[i]:>12.2f} {throughput_mbps[i]:>11.2f} {latency_ms[i]:>9.4f}  {sla}")

    print("\n" + "=" * W)
    print("SLA SUMMARY BY UE TYPE")
    print("=" * W)
    print(f"{'Type':<18} {'Req Lat(ms)':>12} {'Req Tput(Mbps)':>15} "
          f"{'Total':>7} {'Pass':>6} {'Fail':>6} {'Pass%':>7}")
    print("-" * W)
    type_set = list(QOS.keys()) + [t for t in set(ue_types) if t not in QOS]
    for ue_type in type_set:
        idxs = [i for i, t in enumerate(ue_types) if t == ue_type]
        if not idxs: continue
        total  = len(idxs)
        passed = sum(1 for i in idxs if sla_pass[i])
        req    = QOS.get(ue_type, {})
        print(f"  {ue_type:<16} "
              f"{str(req.get('latency_ms','—')):>12} "
              f"{str(req.get('throughput_mbps','—')):>15} "
              f"{total:>7} {passed:>6} {total-passed:>6} {100*passed/total:>6.1f}%")

    n_pass = int(sla_pass.sum())
    n_fail = num_rx - n_pass
    print("-" * W)
    print(f"  {'TOTAL':<16} {'':>12} {'':>15} {num_rx:>7} {n_pass:>6} {n_fail:>6} {100*n_pass/num_rx:>6.1f}%")

    print("\n" + "=" * W)
    print("AGGREGATE SUMMARY")
    print("=" * W)
    print(f"  UEs              : {num_rx}")
    print(f"  gNBs             : {num_tx}")
    print(f"  Avg SINR         : {best_sinr_db.mean():.2f} dB"
          + ("  (mean over active subcarriers)" if use_ofdm else ""))
    print(f"  Avg Throughput   : {throughput_mbps.mean():.2f} Mbps/UE")
    print(f"  Total Throughput : {throughput_mbps.sum():.2f} Mbps")
    print(f"  Avg Latency      : {latency_ms.mean():.4f} ms")
    print(f"  Max Latency      : {latency_ms.max():.4f} ms")
    print(f"  Min Latency      : {latency_ms.min():.4f} ms")
    print(f"  SLA Pass Rate    : {100*n_pass/num_rx:.1f}%  ({n_pass}/{num_rx})")
    if use_ofdm:
        print(f"\n  OFDM config      : {NUM_ACTIVE_SC} active SCs  "
              f"Δf={int(SUBCARRIER_SPACING/1e3)} kHz  "
              f"CP efficiency={CP_EFFICIENCY:.4f}  "
              f"Useful BW={USEFUL_BW/1e6:.2f} MHz")

    # ── Write viewer results ──────────────────────────────────────────────────
    results_out = {
        "best_gnb":        best_gnb.tolist(),
        "throughput_mbps": throughput_mbps.tolist(),
        "sinr_db":         best_sinr_db.tolist(),
        "ue_types":        ue_types,
        "sla_pass":        sla_pass.tolist(),
    }
    with open("sim_results.json", "w") as fout:
        json.dump(results_out, fout, indent=2)
    print(f"\n  Results written: sim_results.json  ({num_rx} UEs)")

    gc.collect()


if __name__ == "__main__":
    main()
