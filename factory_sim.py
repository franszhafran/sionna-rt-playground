import os
import json
import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver
import sionna.rt.scene as scenes
import gc

from config_schema import load_config

# QoS requirements per UE type
# latency_ms: maximum tolerated end-to-end latency
# throughput_mbps: minimum required throughput
QOS = {
    "agv":            {"latency_ms": 10.0,  "throughput_mbps":  5.0},
    "robotic_arm":    {"latency_ms":  5.0,  "throughput_mbps":  1.0},
    "vision_camera":  {"latency_ms": 50.0,  "throughput_mbps": 50.0},
    "safety_sensor":  {"latency_ms":  2.0,  "throughput_mbps":  0.1},
    "worker_tablet":  {"latency_ms": 100.0, "throughput_mbps": 10.0},
}


def compute_mrt_beamforming(h_eff, tx_idx, rx_idx):
    h_pair = h_eff[rx_idx, :, tx_idx, :]
    w_mrt = torch.conj(h_pair[0, :])
    w_mrt_norm = w_mrt / (torch.norm(w_mrt) + 1e-10)
    received_signal = torch.abs(torch.sum(h_pair[0, :] * w_mrt_norm))
    power_db = 20 * torch.log10(received_signal + 1e-10)
    return power_db, w_mrt_norm


def compute_mmse_beamforming(h_eff, tx_idx, noise_var=1e-8):
    num_rx = h_eff.shape[0]
    H = h_eff[:, 0, tx_idx, :]
    H_hermit = H.conj().T
    HH_hermit = torch.matmul(H, H_hermit)
    noise_matrix = noise_var * torch.eye(num_rx, dtype=H.dtype, device=H.device)
    regularized = HH_hermit + noise_matrix
    try:
        inv_regularized = torch.linalg.inv(regularized)
    except:
        inv_regularized = torch.linalg.pinv(regularized)
    W_mmse = torch.matmul(H_hermit, inv_regularized)
    for ue_idx in range(num_rx):
        w_norm = torch.norm(W_mmse[:, ue_idx])
        if w_norm > 1e-10:
            W_mmse[:, ue_idx] = W_mmse[:, ue_idx] / w_norm
    powers_db = []
    for ue_idx in range(num_rx):
        h_ue = h_eff[ue_idx, 0, tx_idx, :]
        w_ue = W_mmse[:, ue_idx]
        signal = torch.abs(torch.sum(h_ue * w_ue))
        interference = 0.0
        for other_ue in range(num_rx):
            if other_ue != ue_idx:
                w_other = W_mmse[:, other_ue]
                interference += torch.abs(torch.sum(h_ue * w_other)) ** 2
        sinr = signal ** 2 / (interference + noise_var)
        power_db = 10 * torch.log10(sinr + 1e-10)
        powers_db.append(power_db)
    return powers_db, W_mmse


def generate_statistical_channel(num_tx, num_rx, num_tx_ant, num_rx_ant,
                                 tx_positions, rx_positions,
                                 frequency, velocity=0.0):
    h_stat = torch.zeros(num_rx, num_rx_ant, num_tx, num_tx_ant, dtype=torch.complex64)
    for tx_idx in range(num_tx):
        for rx_idx in range(num_rx):
            tx_pos = np.array(tx_positions[tx_idx])
            rx_pos = np.array(rx_positions[rx_idx])
            distance = np.linalg.norm(tx_pos - rx_pos)
            freq_ghz = frequency / 1e9
            if distance < 1.0:
                distance = 1.0
            path_loss_db = 31.84 + 21.50 * np.log10(distance) + 19.00 * np.log10(freq_ghz)
            path_loss_linear = 10 ** (-path_loss_db / 20)
            real_part = torch.randn(num_rx_ant, num_tx_ant) / np.sqrt(2)
            imag_part = torch.randn(num_rx_ant, num_tx_ant) / np.sqrt(2)
            fading = torch.complex(real_part, imag_part)
            h_stat[rx_idx, :, tx_idx, :] = path_loss_linear * fading
    return h_stat


def print_factory_layout(tx_positions, rx_positions):
    all_pos = list(tx_positions) + list(rx_positions)
    x_max = max(p[0] for p in all_pos)
    y_max = max(p[1] for p in all_pos)
    # Scale so grid is at most 60 cols × 36 rows
    cell = max(1, int(max(x_max / 60, y_max / 36)))
    W = int(x_max / cell) + 2
    H = int(y_max / cell) + 2
    grid = [['.' for _ in range(W)] for _ in range(H)]

    for i, pos in enumerate(tx_positions):
        c, r = int(round(pos[0] / cell)), int(round(pos[1] / cell))
        if 0 <= r < H and 0 <= c < W:
            grid[r][c] = 'G'

    for pos in rx_positions:
        c, r = int(round(pos[0] / cell)), int(round(pos[1] / cell))
        if 0 <= r < H and 0 <= c < W and grid[r][c] != 'G':
            grid[r][c] = 'U'

    print("\n" + "=" * 70)
    print(f"FACTORY FLOOR LAYOUT  (each cell ≈ {cell}m)  G=gNB  U=UE")
    print("=" * 70)
    for row_y in range(H - 1, -1, -1):
        print(f"{row_y*cell:4d}|{''.join(grid[row_y])}|")
    print("     " + "-" * W)
    print("     " + "".join(str((c * cell // 10) % 10) for c in range(W)))
    print("     x-axis (metres)")

    print("\n--- gNB Positions ---")
    print(f"  {'ID':<8} {'x':>7} {'y':>7} {'z':>6}")
    for i, pos in enumerate(tx_positions):
        print(f"  gNB-{i:<4} {pos[0]:>7.1f} {pos[1]:>7.1f} {pos[2]:>6.1f}")

    print("\n--- Static UE Positions ---")
    print(f"  {'ID':<10} {'x':>7} {'y':>7} {'z':>6}")
    for i, pos in enumerate(rx_positions):
        print(f"  UE-{i:<7} {pos[0]:>7.1f} {pos[1]:>7.1f} {pos[2]:>6.1f}")


def main():
    print("Loading configuration...")
    config = load_config("config.json")
    # load ue_types separately (not in pydantic schema to stay backwards-compatible)
    with open("config.json") as f:
        raw = json.load(f)
    ue_types = raw.get("ue_types", [])
    print("Configuration validated.\n")

    bf_method = config.beamforming_method
    noise_var = config.noise_variance
    use_statistical = getattr(config, 'use_statistical_channel', False)

    print(f"Scene          : {config.scene}")
    print(f"Frequency      : {config.frequency/1e9:.2f} GHz")
    print(f"Beamforming    : {bf_method}")
    print(f"Channel model  : {'Statistical 3GPP InF-SH' if use_statistical else 'Ray Tracing'}")

    scene_ref = config.scene
    if "/" in scene_ref or scene_ref.endswith(".xml"):
        scene = load_scene(scene_ref)
    else:
        scene = load_scene(getattr(scenes, scene_ref))

    num_tx_ant = config.tx_array.rows * config.tx_array.cols
    num_rx_ant = config.rx_array.rows * config.rx_array.cols

    scene.tx_array = PlanarArray(
        num_rows=config.tx_array.rows,
        num_cols=config.tx_array.cols,
        vertical_spacing=config.tx_array.spacing,
        horizontal_spacing=config.tx_array.spacing,
        pattern="iso",
        polarization="V"
    )
    scene.rx_array = PlanarArray(
        num_rows=config.rx_array.rows,
        num_cols=config.rx_array.cols,
        vertical_spacing=config.rx_array.spacing,
        horizontal_spacing=config.rx_array.spacing,
        pattern="iso",
        polarization="V"
    )

    tx_positions = config.transmitters
    rx_positions = config.static_receivers
    num_tx = len(tx_positions)
    num_rx = len(rx_positions)

    for i, pos in enumerate(tx_positions):
        tx = Transmitter(name=f"gnb-{i}", position=pos)
        scene.add(tx)

    for i, pos in enumerate(rx_positions):
        rx = Receiver(name=f"ue-{i}", position=pos)
        scene.add(rx)

    scene.frequency = config.frequency

    # --- Layout ---
    print_factory_layout(tx_positions, rx_positions)

    # --- Channel ---
    print("\n\n=== Computing Channels ===")
    if use_statistical:
        h_eff = generate_statistical_channel(
            num_tx, num_rx, num_tx_ant, num_rx_ant,
            tx_positions, rx_positions, config.frequency
        )
    else:
        path_solver = PathSolver()
        paths = path_solver(scene, max_depth=config.max_depth)
        a_tuple = paths.a
        a_complex = np.array(a_tuple[0]) + 1j * np.array(a_tuple[1])
        h = torch.from_numpy(a_complex).to(torch.complex64)
        h_eff = h.sum(dim=-1)

    # --- Beamforming: collect SINR matrix [num_rx x num_tx] ---
    print(f"Computing {bf_method} beamforming...")
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

    # --- Per-UE metrics ---
    bandwidth = 20e6  # 20 MHz
    slot_ms = 0.5     # 5G NR 30kHz SCS slot duration

    best_gnb = np.argmax(sinr_db_matrix, axis=1)
    best_sinr_db = sinr_db_matrix[np.arange(num_rx), best_gnb]
    best_sinr_lin = 10 ** (best_sinr_db / 10)
    throughput_mbps = bandwidth * np.log2(1 + best_sinr_lin) / 1e6

    latency_ms = np.zeros(num_rx)
    for rx_idx in range(num_rx):
        gn = best_gnb[rx_idx]
        dist = np.linalg.norm(np.array(rx_positions[rx_idx]) - np.array(tx_positions[gn]))
        prop_ms = dist / 3e8 * 1000
        latency_ms[rx_idx] = prop_ms + slot_ms

    # --- QoS SLA check ---
    sla_pass = np.ones(num_rx, dtype=bool)
    sla_fail_reason = [""] * num_rx
    for i in range(num_rx):
        ue_type = ue_types[i] if i < len(ue_types) else None
        if ue_type and ue_type in QOS:
            req = QOS[ue_type]
            lat_fail = latency_ms[i] > req["latency_ms"]
            tput_fail = throughput_mbps[i] < req["throughput_mbps"]
            if lat_fail or tput_fail:
                sla_pass[i] = False
                reasons = []
                if lat_fail:
                    reasons.append(f"lat>{req['latency_ms']}ms")
                if tput_fail:
                    reasons.append(f"tput<{req['throughput_mbps']}Mbps")
                sla_fail_reason[i] = ",".join(reasons)

    # --- Results table ---
    W = 100
    print("\n" + "=" * W)
    print("PER-UE PERFORMANCE  (best serving gNB)")
    print("=" * W)
    print(f"{'UE':<8} {'Type':<16} {'Best gNB':<9} {'SINR(dB)':>9} {'Tput(Mbps)':>11} {'Lat(ms)':>9}  {'SLA'}")
    print("-" * W)
    for i in range(num_rx):
        x, y = rx_positions[i][0], rx_positions[i][1]
        ue_type = ue_types[i] if i < len(ue_types) else "unknown"
        sla = "PASS" if sla_pass[i] else f"FAIL ({sla_fail_reason[i]})"
        print(f"UE-{i:<5} {ue_type:<16} gNB-{best_gnb[i]:<5} "
              f"{best_sinr_db[i]:>9.2f} {throughput_mbps[i]:>11.2f} {latency_ms[i]:>9.4f}  {sla}")

    # --- SLA summary by type ---
    print("\n" + "=" * W)
    print("SLA SUMMARY BY UE TYPE")
    print("=" * W)
    print(f"{'Type':<18} {'Req Lat(ms)':>12} {'Req Tput(Mbps)':>15} {'Total':>7} {'Pass':>6} {'Fail':>6} {'Pass%':>7}")
    print("-" * W)
    type_set = list(QOS.keys()) + [t for t in set(ue_types) if t not in QOS]
    for ue_type in type_set:
        idxs = [i for i, t in enumerate(ue_types) if t == ue_type]
        if not idxs:
            continue
        total = len(idxs)
        passed = sum(1 for i in idxs if sla_pass[i])
        failed = total - passed
        req = QOS.get(ue_type, {})
        req_lat  = f"{req['latency_ms']}"    if req else "—"
        req_tput = f"{req['throughput_mbps']}" if req else "—"
        pct = 100.0 * passed / total
        print(f"  {ue_type:<16} {req_lat:>12} {req_tput:>15} {total:>7} {passed:>6} {failed:>6} {pct:>6.1f}%")

    n_pass = sla_pass.sum()
    n_fail = num_rx - n_pass
    print("-" * W)
    print(f"  {'TOTAL':<16} {'':>12} {'':>15} {num_rx:>7} {n_pass:>6} {n_fail:>6} {100*n_pass/num_rx:>6.1f}%")

    print("\n" + "=" * W)
    print("AGGREGATE SUMMARY")
    print("=" * W)
    print(f"  UEs            : {num_rx}")
    print(f"  gNBs           : {num_tx}")
    print(f"  Avg SINR       : {best_sinr_db.mean():.2f} dB")
    print(f"  Avg Throughput : {throughput_mbps.mean():.2f} Mbps/UE")
    print(f"  Total Tput     : {throughput_mbps.sum():.2f} Mbps")
    print(f"  Avg Latency    : {latency_ms.mean():.4f} ms")
    print(f"  Max Latency    : {latency_ms.max():.4f} ms")
    print(f"  Min Latency    : {latency_ms.min():.4f} ms")
    print(f"  SLA Pass Rate  : {100*n_pass/num_rx:.1f}%  ({n_pass}/{num_rx})")

    gc.collect()


if __name__ == "__main__":
    main()
