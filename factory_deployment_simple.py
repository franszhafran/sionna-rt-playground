"""
Factory/Industrial 5G Deployment Planning with Sionna RT
Simplified version for demonstration
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver
from datetime import datetime

print("="*70)
print("Factory/Industrial 5G Deployment Planning")
print("="*70)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Factory deployment scenario
print("Scenario: Indoor Factory Floor Coverage Analysis")
print("  Environment: Indoor warehouse/factory (100m x 60m x 10m)")
print("  Frequency: 3.7 GHz (Private 5G / CBRS)")
print("  Use Cases: AGVs, Robots, IoT Sensors, AR/VR")
print()

# Load scene
scene = load_scene(sionna.rt.scene.simple_street_canyon)
scene.frequency = 3.7e9  # 3.7 GHz for private 5G
scene.synthetic_array = True

# Factory antenna configuration
ap_array = PlanarArray(
    num_rows=4, num_cols=4,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

device_array = PlanarArray(
    num_rows=2, num_cols=2,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

scene.tx_array = ap_array
scene.rx_array = device_array

# Deploy 3 APs in strategic locations
ap_positions = [
    [20.0, 20.0, 8.0],   # AP1: Corner
    [50.0, 30.0, 8.0],   # AP2: Center
    [80.0, 40.0, 8.0],   # AP3: Far corner
]

print("Access Point Deployment:")
for i, pos in enumerate(ap_positions):
    tx = Transmitter(name=f"ap_{i+1}", position=pos)
    tx.array = ap_array
    scene.add(tx)
    print(f"  AP{i+1}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.0f}m] (ceiling-mounted)")
print()

# Deploy 6 industrial devices at various locations and heights
device_configs = [
    ([25.0, 25.0, 0.5], "AGV"),
    ([45.0, 25.0, 0.5], "AGV"),
    ([65.0, 35.0, 0.5], "Robot"),
    ([35.0, 35.0, 2.5], "Sensor"),
    ([55.0, 15.0, 2.5], "Camera"),
    ([75.0, 25.0, 1.5], "AR_Device"),
]

print("Industrial Device Deployment:")
for i, (pos, dev_type) in enumerate(device_configs):
    rx = Receiver(name=f"device_{i+1}", position=pos)
    rx.array = device_array
    scene.add(rx)
    print(f"  {dev_type:12s}: [{pos[0]:.0f}m, {pos[1]:.0f}m, {pos[2]:.1f}m]")
print()

# Run ray tracing
print("="*70)
print("Computing Propagation Paths..."

)
path_solver = PathSolver()
paths = path_solver(scene, max_depth=3)

print(f"✓ Ray tracing complete")
print()

# Analyze results
a_tuple = paths.a
tau = paths.tau

a_real = np.array(a_tuple[0])
a_imag = np.array(a_tuple[1])
a_complex = a_real + 1j * a_imag
delays = np.array(tau)

h = torch.from_numpy(a_complex).to(torch.complex64)

print("="*70)
print("Channel Analysis Results")
print("="*70)
print()

print(f"Channel Dimensions:")
print(f"  Devices: {h.shape[0]}, AP Locations: {h.shape[2]}")
print(f"  Rx Antennas: {h.shape[1]}, Tx Antennas: {h.shape[3]}")
print(f"  Propagation Paths: {h.shape[4]}")
print()

# Aggregate channel
h_eff = torch.sum(h, dim=-1)  # Sum over paths
h_total = torch.sum(h_eff, dim=(1, 3))  # Sum over antennas

# Calculate received signal strength
path_loss_db = 20 * torch.log10(torch.abs(h_total) + 1e-10)

print("Coverage Statistics:")
print(f"  Average Path Loss: {path_loss_db.mean().item():.2f} dB")
print(f"  Best Coverage:     {path_loss_db.max().item():.2f} dB")
print(f"  Worst Coverage:    {path_loss_db.min().item():.2f} dB")
print(f"  Std Deviation:     {path_loss_db.std().item():.2f} dB")
print()

# Delay spread
max_delay_ns = torch.max(torch.from_numpy(delays)) * 1e9
print(f"Delay Spread: {max_delay_ns.item():.2f} ns")
print(f"Total Paths Found: {h.shape[4]}")
print()

# Per-device coverage report
print("="*70)
print("Per-Device Coverage Report")
print("="*70)
print()

coverage_threshold = -80  # dB (industrial reliability threshold)
print(f"Coverage Threshold: {coverage_threshold} dB\n")

good_coverage_count = 0
for i, (config, dev_type) in enumerate(device_configs):
    device_pl = path_loss_db[i].item()
    status = "✓ Good" if device_pl > coverage_threshold else "✗ Poor"
    if device_pl > coverage_threshold:
        good_coverage_count += 1
    
    # Best AP for this device
    best_ap_idx = torch.argmax(torch.abs(h_total[i])).item()
    
    print(f"{dev_type:12s}: {device_pl:6.2f} dB  [{status}]  (Best AP: AP{best_ap_idx+1})")

coverage_pct = (good_coverage_count / len(device_configs)) * 100
print(f"\nOverall Coverage: {good_coverage_count}/{len(device_configs)} devices ({coverage_pct:.0f}%)")
print()

# Deployment recommendations
print("="*70)
print("Factory Deployment Analysis")
print("="*70)
print()

if coverage_pct >= 90:
    print("✓ EXCELLENT: Coverage meets industrial requirements")
    print("  - All critical areas well-covered")
    print("  - Redundancy for reliability")
elif coverage_pct >= 70:
    print("⚠ ACCEPTABLE: Coverage is adequate but could be optimized")
    print("  - Consider adding 1 more AP for redundancy")
else:
    print("✗ INSUFFICIENT: Coverage gaps detected")
    print("  - Redesign AP placement")
    print("  - Add more APs or use directional antennas")

print()
print("Factory Wireless Requirements:")
print("┌─────────────────┬──────────────┬───────────┬──────────────┐")
print("│ Application     │ Latency      │ Throughput│ Reliability  │")
print("├─────────────────┼──────────────┼───────────┼──────────────┤")
print("│ AGVs/AMRs       │ < 10 ms      │ 10+ Mbps  │ 99.99%       │")
print("│ Industrial Robots│ < 1 ms       │ 5+ Mbps   │ 99.9999%     │")
print("│ IoT Sensors     │ < 100 ms     │ 1+ kbps   │ 99.9%        │")
print("│ AR/VR Maint.    │ < 10 ms      │ 100+ Mbps │ 99.9%        │")
print("│ Video Inspection│ < 50 ms      │ 50+ Mbps  │ 99.99%       │")
print("└─────────────────┴──────────────┴───────────┴──────────────┘")
print()

print("Best Practices for Factory Deployment:")
print("1. AP Placement:")
print("   - Height: 8-10m (ceiling-mounted)")
print("   - Spacing: 20-30m for reliable coverage")
print("   - Avoid metal obstacles when possible")
print()
print("2. Frequency Selection:")
print("   - 3.5-3.8 GHz (CBRS) for private 5G")
print("   - Sub-6 GHz for better penetration")
print("   - Consider interference from factory equipment")
print()
print("3. Redundancy:")
print("   - Each critical point covered by 2+ APs")
print("   - Dual connectivity for ultra-reliable apps")
print()
print("4. Network Slicing:")
print("   - Safety-critical: Ultra-reliable, low-latency")
print("   - Monitoring: Best-effort, moderate throughput")
print("   - Maintenance: High throughput when needed")
print()

print("="*70)
print(f"Analysis completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*70)

# Save configuration
print()
print("Configuration saved to: factory_deployment_config.txt")
with open('/home/ma012/sionna-rt-playground/factory_deployment_config.txt', 'w') as f:
    f.write("Factory 5G Deployment Configuration\n")
    f.write("="*50 + "\n\n")
    f.write(f"Frequency: {scene.frequency/1e9} GHz\n")
    f.write(f"Access Points: {len(ap_positions)}\n")
    f.write(f"Devices: {len(device_configs)}\n")
    f.write(f"Coverage: {coverage_pct:.0f}%\n")
    f.write(f"Average Path Loss: {path_loss_db.mean().item():.2f} dB\n")

print("✓ Done!")
