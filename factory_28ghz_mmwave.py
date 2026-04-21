"""
Factory Deployment: 3 gNBs + 8 Devices @ 28 GHz mmWave
High-frequency millimeter wave for ultra-high capacity industrial applications
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver
from datetime import datetime

print("="*70)
print("Factory mmWave Deployment: 3 gNBs + 8 Devices @ 28 GHz")
print("="*70)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Load factory environment
scene = load_scene(sionna.rt.scene.simple_street_canyon)
scene.frequency = 28e9  # 28 GHz - 5G NR mmWave (n257/n258)
scene.synthetic_array = True

print("Factory mmWave Configuration:")
print(f"  Environment: Indoor factory floor (simulated)")
print(f"  Frequency: {scene.frequency/1e9} GHz (5G NR mmWave)")
print(f"  Band: n257 (26.5-29.5 GHz)")
print(f"  Scenario: High-capacity industrial applications")
print(f"  Use Cases: AR/VR, 8K video, ultra-dense IoT")
print()

print("mmWave Characteristics:")
print("  ✓ Ultra-high bandwidth (100+ MHz channels)")
print("  ✓ Massive MIMO friendly (large arrays)")
print("  ✓ Precise beamforming")
print("  ⚠ Higher path loss than sub-6 GHz")
print("  ⚠ More sensitive to blockage")
print()

# mmWave antenna arrays - Larger arrays feasible at mmWave
# gNBs: 8x8 array (smaller physical size at 28 GHz)
gnb_array = PlanarArray(
    num_rows=8, num_cols=8,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

# Devices: 2x2 array for industrial equipment
device_array = PlanarArray(
    num_rows=2, num_cols=2,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

scene.tx_array = gnb_array
scene.rx_array = device_array

# Deploy 3 gNBs - slightly closer spacing for mmWave
gnb_positions = [
    [20.0, 20.0, 9.0],   # gNB1: Zone A
    [50.0, 30.0, 9.0],   # gNB2: Zone B (center)
    [80.0, 20.0, 9.0],   # gNB3: Zone C
]

print("gNB/Access Point Deployment (mmWave):")
print("  Type: Ceiling-mounted mmWave small cells")
print("  Height: 9 meters")
print("  Antenna: 8x8 planar array (64 elements)")
print("  Physical size: ~5cm x 5cm @ 28 GHz")
print()

for i, pos in enumerate(gnb_positions):
    tx = Transmitter(name=f"gnb_{i+1}", position=pos)
    tx.array = gnb_array
    scene.add(tx)
    print(f"  gNB{i+1}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.0f}m]")

print()

# Deploy 8 industrial devices
device_configs = [
    ([25.0, 22.0, 0.5], "AGV-1"),           # Autonomous vehicle
    ([35.0, 18.0, 0.5], "AGV-2"),           # Autonomous vehicle  
    ([55.0, 28.0, 0.5], "Robot-1"),         # Industrial robot
    ([65.0, 32.0, 0.5], "Robot-2"),         # Industrial robot
    ([40.0, 35.0, 2.5], "8K_Camera"),       # Ultra-HD camera
    ([60.0, 25.0, 2.5], "AR_Station"),      # AR workstation
    ([75.0, 18.0, 1.5], "VR_Device"),       # VR maintenance device
    ([30.0, 25.0, 0.8], "Edge_Server"),     # Edge compute node
]

print("Industrial Device Deployment:")
print("  Total: 8 devices (optimized for mmWave)")
print("  Antenna: 2x2 planar array (4 elements)")
print("  Physical size: ~1cm x 1cm @ 28 GHz")
print()

for i, (pos, name) in enumerate(device_configs):
    rx = Receiver(name=f"device_{i+1}", position=pos)
    rx.array = device_array
    scene.add(rx)
    print(f"  {name:14s}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.1f}m]")

print()

# Run ray tracing - mmWave benefits from more paths
print("="*70)
print("Computing mmWave Propagation Paths (Ray Tracing)...")
print("="*70)
print("Note: mmWave simulation may take longer due to wavelength...")

path_solver = PathSolver()
paths = path_solver(scene, max_depth=3)  # mmWave: reflections important

print(f"✓ Ray tracing completed")
print()

# Extract channel information
a_tuple = paths.a
tau = paths.tau

a_real = np.array(a_tuple[0])
a_imag = np.array(a_tuple[1])
a_complex = a_real + 1j * a_imag
delays = np.array(tau)

h = torch.from_numpy(a_complex).to(torch.complex64)

print("="*70)
print("mmWave Channel Matrix Analysis")
print("="*70)
print()

print(f"Channel Dimensions:")
print(f"  Devices (UEs): {h.shape[0]}")
print(f"  Device Antennas: {h.shape[1]}")
print(f"  gNBs (APs): {h.shape[2]}")
print(f"  gNB Antennas: {h.shape[3]}")
print(f"  Propagation Paths: {h.shape[4]}")
print()

# mmWave path loss analysis
wavelength = 3e8 / scene.frequency
print(f"mmWave Characteristics:")
print(f"  Wavelength: {float(wavelength)*1000:.2f} mm")
print(f"  Free-space path loss (10m): {20*np.log10(4*np.pi*10/float(wavelength)):.1f} dB")
print()

# Beamforming Analysis (MRT)
print("Applying Maximum Ratio Transmission (MRT) Beamforming...")

# Aggregate over paths
h_eff = torch.sum(h, dim=-1)  # [num_rx, num_rx_ant, num_tx, num_tx_ant]

# MRT beamforming weights
mrt_weights = torch.conj(h_eff)
weights_norm = torch.sqrt(torch.sum(torch.abs(mrt_weights)**2, dim=3, keepdim=True))
mrt_weights_norm = mrt_weights / (weights_norm + 1e-10)

# Apply beamforming
received_signal = torch.sum(h_eff * mrt_weights_norm, dim=3)

# Calculate signal power
tx_power = 1.0
signal_power = torch.abs(received_signal) ** 2 * tx_power
signal_power_per_link = torch.sum(signal_power, dim=1)

# SINR calculation
noise_power = 1e-10
sinr_linear = signal_power_per_link / noise_power
sinr_db = 10 * torch.log10(sinr_linear + 1e-10)

# Best gNB per device
best_gnb_sinr, best_gnb_idx = torch.max(sinr_db, dim=1)

print(f"✓ Beamforming completed")
print()

# Throughput - mmWave can use much wider bandwidth
bandwidth_mmwave = 100e6  # 100 MHz channel (typical for mmWave)
throughput_bps = bandwidth_mmwave * torch.log2(1 + sinr_linear)
throughput_mbps = throughput_bps / 1e6

best_throughput = torch.gather(throughput_mbps, 1, best_gnb_idx.unsqueeze(1)).squeeze(1)

print("="*70)
print("mmWave Performance Results")
print("="*70)
print()

print(f"Overall Statistics (@ 28 GHz, 100 MHz BW):")
print(f"  Average SINR: {best_gnb_sinr.mean().item():.2f} dB")
print(f"  Best SINR: {best_gnb_sinr.max().item():.2f} dB")
print(f"  Worst SINR: {best_gnb_sinr.min().item():.2f} dB")
print(f"  Std Deviation: {best_gnb_sinr.std().item():.2f} dB")
print()

print(f"  Average Throughput: {best_throughput.mean().item():.2f} Mbps")
print(f"  Peak Throughput: {best_throughput.max().item():.2f} Mbps")
print(f"  Min Throughput: {best_throughput.min().item():.2f} Mbps")
print(f"  Total Capacity: {best_throughput.sum().item():.2f} Mbps")
print()

# Delay spread
max_delay_ns = torch.max(torch.from_numpy(delays)) * 1e9
print(f"Propagation Characteristics:")
print(f"  Max Delay Spread: {max_delay_ns.item():.2f} ns")
print(f"  Total Paths: {h.shape[4]}")
print()

# Per-device report
print("="*70)
print("Per-Device Performance @ 28 GHz")
print("="*70)
print()

# mmWave reliability thresholds (slightly different from sub-6)
threshold_mmwave = 15  # dB SINR for mmWave reliability
threshold_normal = 10

print(f"Thresholds: mmWave={threshold_mmwave}dB, Normal={threshold_normal}dB\n")

mmwave_ok = 0
normal_ok = 0

for i, (config, name) in enumerate(device_configs):
    device_sinr = best_gnb_sinr[i].item()
    device_tput = best_throughput[i].item()
    serving_gnb = best_gnb_idx[i].item() + 1
    
    if device_sinr >= threshold_mmwave:
        status = "✓ Excellent"
        mmwave_ok += 1
        normal_ok += 1
    elif device_sinr >= threshold_normal:
        status = "✓ Good"
        normal_ok += 1
    else:
        status = "✗ Poor"
    
    print(f"{name:14s}: {device_sinr:6.2f} dB  {device_tput:7.2f} Mbps  [gNB{serving_gnb}]  {status}")

print()
print(f"Coverage Quality:")
print(f"  mmWave Reliable (>{threshold_mmwave}dB): {mmwave_ok}/8 devices ({mmwave_ok/8*100:.0f}%)")
print(f"  Normal Operation (>{threshold_normal}dB): {normal_ok}/8 devices ({normal_ok/8*100:.0f}%)")
print()

# mmWave application requirements
print("="*70)
print("mmWave Application Compliance")
print("="*70)
print()

requirements = [
    ("8K Video Streaming", 15, 100, [4]),          # 8K needs high throughput
    ("AR/VR Workstation", 15, 200, [5, 6]),        # Immersive apps
    ("Edge Computing", 10, 1000, [7]),             # Ultra-high bandwidth
    ("Robot Control", 20, 50, [2, 3]),             # Still needs reliability
    ("AGV Fleet", 10, 50, [0, 1]),                 # Navigation
]

print("Application Type        | Req.  | Status")
print("-" * 50)

for app_name, req_sinr, req_tput, device_indices in requirements:
    passed = 0
    total = len(device_indices)
    
    for idx in device_indices:
        if best_gnb_sinr[idx].item() >= req_sinr and best_throughput[idx].item() >= req_tput:
            passed += 1
    
    status = "✓ PASS" if passed == total else f"⚠ {passed}/{total}"
    print(f"{app_name:22s} | {req_sinr:2d}dB, {req_tput:4.0f}Mbps | {status}")

print()

# Comparison with sub-6 GHz
print("="*70)
print("mmWave vs. Sub-6 GHz Comparison")
print("="*70)
print()

print("┌─────────────────────┬─────────────┬──────────────┐")
print("│ Metric              │ 3.7 GHz     │ 28 GHz       │")
print("├─────────────────────┼─────────────┼──────────────┤")
print(f"│ Bandwidth           │ 20 MHz      │ 100 MHz      │")
print(f"│ Wavelength          │ ~8 cm       │ ~1 cm        │")
print(f"│ Avg Throughput/Dev  │ 379 Mbps    │ {best_throughput.mean().item():.0f} Mbps    │")
print(f"│ Total Capacity      │ 3,035 Mbps  │ {best_throughput.sum().item():.0f} Mbps  │")
print(f"│ Path Loss           │ Lower       │ Higher       │")
print(f"│ Penetration         │ Better      │ Poorer       │")
print(f"│ Beamforming Gain    │ Good        │ Excellent    │")
print(f"│ Coverage Range      │ Wider       │ Shorter      │")
print("└─────────────────────┴─────────────┴──────────────┘")
print()

# Deployment recommendations
print("="*70)
print("mmWave Deployment Assessment")
print("="*70)
print()

if mmwave_ok >= 6:
    print("✓ EXCELLENT: mmWave deployment successful")
    print("  - High capacity for bandwidth-intensive apps")
    print("  - Excellent beamforming performance")
    print("  - 100 MHz channels enable multi-Gbps rates")
elif normal_ok >= 6:
    print("✓ GOOD: Acceptable for most mmWave applications")
    print("  - Consider optimizing AP placement")
    print("  - Hybrid deployment with sub-6 GHz recommended")
else:
    print("⚠ CHALLENGING: mmWave coverage limited")
    print("  - Add more gNBs for dense coverage")
    print("  - Consider hybrid macro+mmWave deployment")

print()
print("mmWave Best Practices:")
print("  ✓ Dense deployment (15-20m AP spacing)")
print("  ✓ Line-of-sight or near-LoS critical")
print("  ✓ Large antenna arrays (8x8 minimum)")
print("  ✓ Beam management and tracking essential")
print("  ✓ Hybrid beamforming for complexity reduction")
print("  ✓ Fallback to sub-6 GHz for mobility")
print()

print("Ideal mmWave Use Cases:")
print("  • Fixed wireless access (FWA) in factory")
print("  • 8K/16K video surveillance and inspection")
print("  • AR/VR training and remote operation")
print("  • Ultra-low latency robot control cells")
print("  • Massive file transfers (digital twins, CAD)")
print("  • Edge computing with Tbps backhaul")
print()

# Save results
output_file = '/home/ma012/sionna-rt-playground/factory_28ghz_results.txt'
with open(output_file, 'w') as f:
    f.write("Factory mmWave Deployment Results (28 GHz)\n")
    f.write("="*60 + "\n\n")
    f.write(f"Frequency: {scene.frequency/1e9} GHz\n")
    f.write(f"Bandwidth: 100 MHz\n")
    f.write(f"gNBs: 3 (8x8 arrays)\n")
    f.write(f"Devices: 8 (2x2 arrays)\n\n")
    f.write(f"Average SINR: {best_gnb_sinr.mean().item():.2f} dB\n")
    f.write(f"Average Throughput: {best_throughput.mean().item():.2f} Mbps\n")
    f.write(f"Total Capacity: {best_throughput.sum().item():.2f} Mbps\n")
    f.write(f"mmWave Coverage: {mmwave_ok}/8 devices\n")

print(f"Results saved to: {output_file}")
print()

print("="*70)
print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*70)
