"""
Factory Deployment @ 28 GHz mmWave - 3 gNBs + 8 Devices
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver
from datetime import datetime

print("="*70)
print("Factory mmWave @ 28 GHz: 3 gNBs + 8 Devices")
print("="*70)
print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
print()

# Load scene
scene = load_scene(sionna.rt.scene.simple_street_canyon)
scene.frequency = 28e9  # 28 GHz mmWave
scene.synthetic_array = True

freq_ghz = 28.0
wavelength_mm = (3e8 / 28e9) * 1000  # ~10.7 mm

print(f"Configuration:")
print(f"  Frequency: {freq_ghz} GHz (5G NR n257/n258)")
print(f"  Wavelength: {wavelength_mm:.2f} mm")
print(f"  Bandwidth: 100 MHz (mmWave channel)")
print(f"  Scenario: Ultra-high capacity factory")
print()

# Antenna arrays
gnb_array = PlanarArray(num_rows=8, num_cols=8, vertical_spacing=0.5,
                        horizontal_spacing=0.5, pattern="iso", polarization="V")
device_array = PlanarArray(num_rows=2, num_cols=2, vertical_spacing=0.5,
                           horizontal_spacing=0.5, pattern="iso", polarization="V")

scene.tx_array = gnb_array
scene.rx_array = device_array

# Deploy 3 gNBs
gnb_pos = [[20, 20, 9], [50, 30, 9], [80, 20, 9]]
print("gNBs (mmWave small cells @ 9m):")
for i, pos in enumerate(gnb_pos):
    tx = Transmitter(name=f"gnb_{i+1}", position=pos)
    scene.add(tx)
    print(f"  gNB{i+1}: [{pos[0]}m, {pos[1]}m, {pos[2]}m]")
print()

# Deploy 8 devices
devices = [
    ([25, 22, 0.5], "AGV-1"), ([35, 18, 0.5], "AGV-2"),
    ([55, 28, 0.5], "Robot-1"), ([65, 32, 0.5], "Robot-2"),
    ([40, 35, 2.5], "8K_Camera"), ([60, 25, 2.5], "AR_Station"),
    ([75, 18, 1.5], "VR_Device"), ([30, 25, 0.8], "Edge_Server")
]

print("Devices (8 industrial units):")
for i, (pos, name) in enumerate(devices):
    rx = Receiver(name=f"device_{i+1}", position=pos)
    scene.add(rx)
    print(f"  {name:12s}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.1f}m]")
print()

# Ray tracing
print("="*70)
print("Ray Tracing @ 28 GHz...")
print("="*70)

path_solver = PathSolver()
paths = path_solver(scene, max_depth=3)

print("✓ Complete\n")

# Extract channel
a_tuple = paths.a
a_real, a_imag = np.array(a_tuple[0]), np.array(a_tuple[1])
h = torch.from_numpy(a_real + 1j * a_imag).to(torch.complex64)

print(f"Channel: {h.shape[0]} devices, {h.shape[2]} gNBs, {h.shape[4]} paths\n")

# Beamforming
h_eff = torch.sum(h, dim=-1)
mrt_weights = torch.conj(h_eff)
weights_norm = torch.sqrt(torch.sum(torch.abs(mrt_weights)**2, dim=3, keepdim=True))
mrt_weights_norm = mrt_weights / (weights_norm + 1e-10)
received_signal = torch.sum(h_eff * mrt_weights_norm, dim=3)

# SINR
signal_power = torch.sum(torch.abs(received_signal)**2, dim=1)
noise_power = 1e-10
sinr_linear = signal_power / noise_power
sinr_db = 10 * torch.log10(sinr_linear + 1e-10)

best_sinr, best_gnb = torch.max(sinr_db, dim=1)

# Throughput with 100 MHz BW
bw = 100e6
tput_bps = bw * torch.log2(1 + sinr_linear)
tput_mbps = tput_bps / 1e6
best_tput = torch.gather(tput_mbps, 1, best_gnb.unsqueeze(1)).squeeze(1)

print("="*70)
print("Results @ 28 GHz mmWave")
print("="*70)
print()

print(f"SINR Statistics:")
print(f"  Average: {best_sinr.mean().item():.2f} dB")
print(f"  Best:    {best_sinr.max().item():.2f} dB")
print(f"  Worst:   {best_sinr.min().item():.2f} dB")
print()

print(f"Throughput (100 MHz BW):")
print(f"  Average: {best_tput.mean().item():.2f} Mbps")
print(f"  Peak:    {best_tput.max().item():.2f} Mbps")
print(f"  Total:   {best_tput.sum().item():.2f} Mbps")
print()

print("Per-Device Performance:")
print("-" * 60)
for i, (cfg, name) in enumerate(devices):
    sinr = best_sinr[i].item()
    tput = best_tput[i].item()
    gnb = best_gnb[i].item() + 1
    status = "✓" if sinr > 15 else "⚠"
    print(f"{name:12s}: {sinr:6.2f} dB  {tput:7.2f} Mbps  [gNB{gnb}]  {status}")

print()
coverage = (best_sinr > 15).sum().item()
print(f"Coverage: {coverage}/8 devices above 15 dB ({coverage/8*100:.0f}%)\n")

print("="*70)
print("28 GHz vs. 3.7 GHz Comparison")
print("="*70)
print()
print("┌───────────────┬──────────┬───────────┐")
print("│ Metric        │ 3.7 GHz  │ 28 GHz    │")
print("├───────────────┼──────────┼───────────┤")
print(f"│ Bandwidth     │  20 MHz  │  100 MHz  │")
print(f"│ Wavelength    │  ~81 mm  │  ~11 mm   │")
print(f"│ Avg SINR      │  57 dB   │  {best_sinr.mean().item():.0f} dB     │")
print(f"│ Avg Tput/Dev  │ 379 Mbps │ {best_tput.mean().item():.0f} Mbps   │")
print(f"│ Total Capacity│3,035 Mbps│{best_tput.sum().item():.0f} Mbps │")
print("└───────────────┴──────────┴───────────┘")
print()

print("mmWave Advantages:")
print("  ✓ 5x wider bandwidth (100 vs 20 MHz)")
print("  ✓ Smaller antennas (easier massive MIMO)")
print("  ✓ Precise beamforming")
print("  ✓ Less interference (spatial isolation)")
print()

print("mmWave Challenges:")
print("  ⚠ Higher free-space path loss")
print("  ⚠ Poor penetration through walls")
print("  ⚠ Requires dense deployment")
print("  ⚠ Sensitive to blockage")
print()

print("Best Use Cases for 28 GHz:")
print("  • Fixed wireless in factory (line-of-sight)")
print("  • 8K/16K video streaming")
print("  • AR/VR with ultra-high quality")
print("  • Edge computing backhaul")
print("  • High-speed file transfers")
print()

with open('/home/ma012/sionna-rt-playground/factory_28ghz_results.txt', 'w') as f:
    f.write(f"28 GHz mmWave Results\n")
    f.write(f"Avg SINR: {best_sinr.mean().item():.2f} dB\n")
    f.write(f"Avg Throughput: {best_tput.mean().item():.2f} Mbps\n")
    f.write(f"Total: {best_tput.sum().item():.2f} Mbps\n")

print(f"Completed: {datetime.now().strftime('%H:%M:%S')}")
print("="*70)
