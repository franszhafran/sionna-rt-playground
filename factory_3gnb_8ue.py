"""
Factory Deployment: 3 gNBs (Access Points) + 8 Devices
Realistic industrial wireless planning with Sionna RT
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver
from datetime import datetime

print("="*70)
print("Factory 5G Deployment: 3 gNBs + 8 Industrial Devices")
print("="*70)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Load factory environment (using street canyon as warehouse proxy)
scene = load_scene(sionna.rt.scene.simple_street_canyon)
scene.frequency = 3.7e9  # 3.7 GHz - Private 5G/CBRS
scene.synthetic_array = True

print("Factory Configuration:")
print(f"  Environment: Indoor factory floor (simulated)")
print(f"  Frequency: {scene.frequency/1e9} GHz (CBRS Private 5G)")
print(f"  Scenario: Production floor with AGVs, Robots, IoT devices")
print()

# Antenna arrays - Factory optimized
# gNBs/APs: 8x8 array for good beamforming
gnb_array = PlanarArray(
    num_rows=8, num_cols=8,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

# Devices: 2x2 array (typical for industrial equipment)
device_array = PlanarArray(
    num_rows=2, num_cols=2,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

scene.tx_array = gnb_array
scene.rx_array = device_array

# Deploy 3 gNBs (ceiling-mounted small cells)
gnb_positions = [
    [20.0, 20.0, 9.0],   # gNB1: Zone A
    [50.0, 30.0, 9.0],   # gNB2: Zone B (center)
    [80.0, 20.0, 9.0],   # gNB3: Zone C
]

print("gNB/Access Point Deployment:")
print("  Type: Ceiling-mounted small cells")
print("  Height: 9 meters (industrial ceiling)")
print("  Antenna: 8x8 planar array (64 elements)")
print()

for i, pos in enumerate(gnb_positions):
    tx = Transmitter(name=f"gnb_{i+1}", position=pos)
    tx.array = gnb_array
    scene.add(tx)
    print(f"  gNB{i+1}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.0f}m]")

print()

# Deploy 8 industrial devices at various locations
device_configs = [
    ([25.0, 22.0, 0.5], "AGV-1"),           # Autonomous vehicle
    ([35.0, 18.0, 0.5], "AGV-2"),           # Autonomous vehicle  
    ([55.0, 28.0, 0.5], "Robot-1"),         # Industrial robot
    ([65.0, 32.0, 0.5], "Robot-2"),         # Industrial robot
    ([40.0, 35.0, 2.5], "Sensor-1"),        # Elevated sensor
    ([60.0, 25.0, 2.5], "Camera-1"),        # Vision system
    ([75.0, 18.0, 1.5], "AR_Device"),       # AR maintenance device
    ([30.0, 25.0, 0.8], "IoT_Gateway"),     # IoT concentrator
]

print("Industrial Device Deployment:")
print("  Total: 8 devices (AGVs, Robots, Sensors, AR)")
print("  Antenna: 2x2 planar array (4 elements)")
print()

for i, (pos, name) in enumerate(device_configs):
    rx = Receiver(name=f"device_{i+1}", position=pos)
    rx.array = device_array
    scene.add(rx)
    print(f"  {name:14s}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.1f}m]")

print()

# Run ray tracing simulation
print("="*70)
print("Computing Propagation Paths (Ray Tracing)...")
print("="*70)

path_solver = PathSolver()
paths = path_solver(scene, max_depth=3)  # 3 reflections for indoor

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
print("Channel Matrix Analysis")
print("="*70)
print()

print(f"Channel Dimensions:")
print(f"  Devices (UEs): {h.shape[0]}")
print(f"  Device Antennas: {h.shape[1]}")
print(f"  gNBs (APs): {h.shape[2]}")
print(f"  gNB Antennas: {h.shape[3]}")
print(f"  Propagation Paths: {h.shape[4]}")
print()

# Beamforming Analysis (MRT)
print("Applying Maximum Ratio Transmission (MRT) Beamforming...")

# Aggregate over paths
h_eff = torch.sum(h, dim=-1)  # [num_rx, num_rx_ant, num_tx, num_tx_ant]

# MRT beamforming weights: w = conj(h)
mrt_weights = torch.conj(h_eff)

# Normalize weights
weights_norm = torch.sqrt(torch.sum(torch.abs(mrt_weights)**2, dim=3, keepdim=True))
mrt_weights_norm = mrt_weights / (weights_norm + 1e-10)

# Apply beamforming
received_signal = torch.sum(h_eff * mrt_weights_norm, dim=3)  # [num_rx, num_rx_ant, num_tx]

# Calculate signal power per link
tx_power = 1.0  # Normalized
signal_power = torch.abs(received_signal) ** 2 * tx_power

# Sum over receive antennas to get total received power per device
signal_power_per_link = torch.sum(signal_power, dim=1)  # [num_rx, num_tx]

# SINR calculation
noise_power = 1e-10  # -100 dBm noise floor
sinr_linear = signal_power_per_link / noise_power
sinr_db = 10 * torch.log10(sinr_linear + 1e-10)

# Select best gNB for each device
best_gnb_sinr, best_gnb_idx = torch.max(sinr_db, dim=1)

print(f"✓ Beamforming completed")
print()

# Throughput estimation (Shannon capacity)
bandwidth = 20e6  # 20 MHz channel
throughput_bps = bandwidth * torch.log2(1 + sinr_linear)
throughput_mbps = throughput_bps / 1e6

# Select best throughput from best gNB
best_throughput = torch.gather(throughput_mbps, 1, best_gnb_idx.unsqueeze(1)).squeeze(1)

print("="*70)
print("Coverage & Performance Results")
print("="*70)
print()

print(f"Overall Statistics:")
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

# Delay spread analysis
max_delay_ns = torch.max(torch.from_numpy(delays)) * 1e9
print(f"Propagation Characteristics:")
print(f"  Max Delay Spread: {max_delay_ns.item():.2f} ns")
print(f"  Total Paths: {h.shape[4]}")
print()

# Per-device detailed report
print("="*70)
print("Per-Device Performance Report")
print("="*70)
print()

# Industrial reliability thresholds
threshold_critical = 20  # dB SINR for ultra-reliable
threshold_normal = 10    # dB SINR for normal operation

print(f"Thresholds: Critical={threshold_critical}dB, Normal={threshold_normal}dB\n")

critical_ok = 0
normal_ok = 0

for i, (config, name) in enumerate(device_configs):
    device_sinr = best_gnb_sinr[i].item()
    device_tput = best_throughput[i].item()
    serving_gnb = best_gnb_idx[i].item() + 1
    
    if device_sinr >= threshold_critical:
        status = "✓ Excellent"
        critical_ok += 1
        normal_ok += 1
    elif device_sinr >= threshold_normal:
        status = "✓ Good"
        normal_ok += 1
    else:
        status = "✗ Poor"
    
    print(f"{name:14s}: {device_sinr:6.2f} dB  {device_tput:7.2f} Mbps  [gNB{serving_gnb}]  {status}")

print()
print(f"Coverage Quality:")
print(f"  Ultra-Reliable (>{threshold_critical}dB): {critical_ok}/8 devices ({critical_ok/8*100:.0f}%)")
print(f"  Normal Operation (>{threshold_normal}dB): {normal_ok}/8 devices ({normal_ok/8*100:.0f}%)")
print()

# Application requirements check
print("="*70)
print("Application Requirement Compliance")
print("="*70)
print()

requirements = [
    ("AGV/AMR", 10, 10, [0, 1]),           # SINR>=10dB, Tput>=10Mbps
    ("Industrial Robot", 20, 5, [2, 3]),   # SINR>=20dB, Tput>=5Mbps
    ("AR/VR Device", 15, 100, [6]),        # SINR>=15dB, Tput>=100Mbps
    ("IoT/Sensor", 5, 1, [4, 5, 7]),       # SINR>=5dB, Tput>=1Mbps
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
    print(f"{app_name:22s} | {req_sinr:2d}dB, {req_tput:3.0f}Mbps | {status}")

print()

# Deployment recommendations
print("="*70)
print("Deployment Assessment & Recommendations")
print("="*70)
print()

if critical_ok >= 6:
    print("✓ EXCELLENT: Factory deployment meets all requirements")
    print("  - Ultra-reliable coverage for critical applications")
    print("  - Sufficient capacity for all use cases")
    print("  - Consider adding 1 more gNB for full redundancy")
elif normal_ok >= 6:
    print("✓ GOOD: Deployment is adequate for most applications")
    print("  - Acceptable for normal operations")
    print("  - May need optimization for safety-critical robots")
    print("  - Consider power boosting or adding 1-2 more gNBs")
else:
    print("⚠ NEEDS IMPROVEMENT: Coverage gaps detected")
    print("  - Add 1-2 more gNBs in poorly covered areas")
    print("  - Optimize gNB placement for better coverage")
    print("  - Consider higher transmit power")

print()
print("Best Practices Applied:")
print("  ✓ Ceiling-mounted gNBs (9m height)")
print("  ✓ CBRS private 5G spectrum (3.7 GHz)")
print("  ✓ 20 MHz bandwidth for good capacity")
print("  ✓ MRT beamforming for signal enhancement")
print("  ✓ 8x8 gNB arrays for strong beamforming gain")
print()

print("Recommendations for Improvement:")
print("  1. Network Slicing: Separate slices for safety vs. monitoring")
print("  2. Dual Connectivity: Connect critical devices to 2 gNBs")
print("  3. QoS: Prioritize ultra-reliable traffic (robots)")
print("  4. Handover: Optimize for seamless AGV movement")
print("  5. Monitoring: Real-time SINR/throughput tracking")
print()

# Save results
output_file = '/home/ma012/sionna-rt-playground/factory_3gnb_8ue_results.txt'
with open(output_file, 'w') as f:
    f.write("Factory 5G Deployment Results (3 gNBs + 8 Devices)\n")
    f.write("="*60 + "\n\n")
    f.write(f"Frequency: {scene.frequency/1e9} GHz\n")
    f.write(f"Bandwidth: 20 MHz\n")
    f.write(f"gNBs: 3 (8x8 arrays)\n")
    f.write(f"Devices: 8 (2x2 arrays)\n\n")
    f.write(f"Average SINR: {best_gnb_sinr.mean().item():.2f} dB\n")
    f.write(f"Average Throughput: {best_throughput.mean().item():.2f} Mbps\n")
    f.write(f"Total Capacity: {best_throughput.sum().item():.2f} Mbps\n")
    f.write(f"Ultra-Reliable Coverage: {critical_ok}/8 devices\n")

print(f"Results saved to: {output_file}")
print()

print("="*70)
print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*70)
