"""
Factory/Industrial 5G Deployment Planning with Sionna RT
Demonstrates wireless coverage planning for industrial environments
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver
from datetime import datetime

print("="*70)
print("Factory/Industrial 5G Deployment with Sionna RT")
print("="*70)
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Factory deployment scenarios
print("Deployment Scenarios:")
print("1. Large outdoor factory campus (munich scene)")
print("2. Indoor warehouse/factory floor (street_canyon as proxy)")
print("3. Mixed indoor-outdoor industrial complex")
print()

# Let's simulate Scenario 2: Indoor warehouse/factory floor
print("="*70)
print("Scenario: Indoor Factory Floor Coverage")
print("="*70)
print()

# Load scene (using street_canyon as warehouse proxy)
scene = load_scene(sionna.rt.scene.simple_street_canyon)

# Factory-specific parameters
scene.frequency = 3.7e9  # 3.7 GHz (common for private 5G/Industry 4.0)
scene.synthetic_array = True

print(f"✓ Scene loaded: Indoor factory environment (proxy)")
print(f"✓ Frequency: {scene.frequency/1e9} GHz (Private 5G)")
print()

# Factory deployment pattern: Ceiling-mounted access points
print("Access Point Configuration:")
print("  Type: Ceiling-mounted small cells")
print("  Pattern: Grid deployment for uniform coverage")
print("  Height: 8-10 meters (typical factory ceiling)")
print()

# Create factory-grade antenna arrays
# Access points: 4x4 array (moderate beamforming)
ap_array = PlanarArray(
    num_rows=4, num_cols=4,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

# Industrial devices: 2x2 array (IoT, AGVs, robots)
device_array = PlanarArray(
    num_rows=2, num_cols=2,
    vertical_spacing=0.5, horizontal_spacing=0.5,
    pattern="iso", polarization="V"
)

scene.tx_array = ap_array
scene.rx_array = device_array

# Deploy access points in grid pattern
# Factory floor: 100m x 60m, AP spacing: 30m
ap_positions = [
    [15.0, 15.0, 8.0],   # AP1: Northwest
    [45.0, 15.0, 8.0],   # AP2: North
    [75.0, 15.0, 8.0],   # AP3: Northeast
    [15.0, 45.0, 8.0],   # AP4: Southwest
    [45.0, 45.0, 8.0],   # AP5: Center
    [75.0, 45.0, 8.0],   # AP6: Southeast
]

print(f"Deploying {len(ap_positions)} Access Points:")
for i, pos in enumerate(ap_positions):
    tx = Transmitter(name=f"ap_{i+1}", position=pos)
    tx.array = ap_array
    scene.add(tx)
    print(f"  AP{i+1}: Position [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}]m")

print()

# Deploy industrial devices
# Simulating: AGVs, robots, IoT sensors at different heights
device_positions = [
    # Ground-level devices (AGVs, robots)
    [20.0, 20.0, 0.5],  [40.0, 20.0, 0.5],  [60.0, 20.0, 0.5],
    [20.0, 40.0, 0.5],  [40.0, 40.0, 0.5],  [60.0, 40.0, 0.5],
    # Elevated sensors (on equipment)
    [30.0, 25.0, 2.5],  [50.0, 25.0, 2.5],  [70.0, 25.0, 2.5],
    [30.0, 35.0, 2.5],  [50.0, 35.0, 2.5],  [70.0, 35.0, 2.5],
]

print(f"Deploying {len(device_positions)} Industrial Devices:")
device_types = [
    "AGV", "AGV", "AGV", "Robot", "Robot", "Robot",
    "Sensor", "Sensor", "Sensor", "Camera", "Camera", "Camera"
]

for i, (pos, dev_type) in enumerate(zip(device_positions, device_types)):
    rx = Receiver(name=f"device_{i+1}", position=pos)
    rx.array = device_array
    scene.add(rx)
    if i < 6:  # Print first 6 only
        print(f"  {dev_type} {i+1}: Position [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}]m")

print(f"  ... and {len(device_positions)-6} more devices")
print()

# Run ray tracing
print("="*70)
print("Computing Propagation Paths...")
print("="*70)

path_solver = PathSolver()
paths = path_solver(scene, max_depth=4)  # Factory: more reflections

print(f"✓ Ray tracing complete")
print()

# Analyze coverage
print("="*70)
print("Factory Coverage Analysis")
print("="*70)
print()

# Extract channel information
a_tuple = paths.a
tau = paths.tau

a_real = np.array(a_tuple[0])
a_imag = np.array(a_tuple[1])
a_complex = a_real + 1j * a_imag
delays = np.array(tau)

# Convert to torch
h = torch.from_numpy(a_complex).to(torch.complex64)

print(f"Channel Matrix Shape: {h.shape}")
print(f"  - Receivers (devices): {h.shape[0]}")
print(f"  - Receiver antennas: {h.shape[1]}")
print(f"  - Transmitters (APs): {h.shape[2]}")
print(f"  - Transmitter antennas: {h.shape[3]}")
print(f"  - Propagation paths: {h.shape[4]}")
print()

# Aggregate over antennas and paths
h_eff = torch.sum(h, dim=-1)  # Sum over paths
h_total = torch.sum(h_eff, dim=(1, 3))  # Sum over antennas

# Calculate path loss for each device
path_loss = 20 * torch.log10(torch.abs(h_total) + 1e-10)

print("Coverage Statistics:")
print(f"  Average Path Loss: {path_loss.mean().item():.2f} dB")
print(f"  Best Coverage: {path_loss.max().item():.2f} dB")
print(f"  Worst Coverage: {path_loss.min().item():.2f} dB")
print(f"  Std Deviation: {path_loss.std().item():.2f} dB")
print()

# Delay spread analysis (for industrial reliability)
max_delay = torch.max(torch.from_numpy(delays)) * 1e9  # Convert to ns
print(f"Delay Spread Analysis:")
print(f"  Maximum delay: {max_delay.item():.2f} ns")
print(f"  Total paths found: {h.shape[4]}")
print()

# Coverage quality assessment
coverage_threshold = -100  # dB (typical for reliable industrial comms)
good_coverage = (path_loss > coverage_threshold).sum().item()
coverage_percentage = (good_coverage / len(device_positions)) * 100

print("Coverage Quality:")
print(f"  Threshold: {coverage_threshold} dB")
print(f"  Devices with good coverage: {good_coverage}/{len(device_positions)}")
print(f"  Coverage percentage: {coverage_percentage:.1f}%")
print()

# Per-device analysis (first 6)
print("Per-Device Analysis (sample):")
print("-" * 50)
for i in range(min(6, len(device_positions))):
    device_pl = path_loss[i].item()
    status = "✓ Good" if device_pl > coverage_threshold else "✗ Poor"
    print(f"  {device_types[i]} {i+1}: {device_pl:6.2f} dB [{status}]")

print()
print("="*70)
print("Factory Deployment Recommendations")
print("="*70)
print()

if coverage_percentage >= 95:
    print("✓ EXCELLENT: Current AP placement provides excellent coverage")
elif coverage_percentage >= 85:
    print("✓ GOOD: Coverage is acceptable, minor optimization possible")
elif coverage_percentage >= 70:
    print("⚠ FAIR: Consider adding 1-2 more APs for better coverage")
else:
    print("✗ POOR: Significant coverage gaps - redesign AP placement")

print()
print("Industrial Deployment Best Practices:")
print("1. AP Height: 8-10m for ceiling mounting")
print("2. AP Spacing: 20-30m for reliable coverage")
print("3. Frequency: 3.5-3.8 GHz (CBRS/Private 5G)")
print("4. Redundancy: Ensure each point covered by 2+ APs")
print("5. Metal obstacles: Account for additional 10-20 dB loss")
print()

print("Use Cases:")
print("- AGVs/AMRs: Require <10ms latency, >10 Mbps throughput")
print("- Industrial robots: Ultra-reliable (99.999%), <1ms latency")
print("- IoT sensors: Low power, periodic reporting (kbps sufficient)")
print("- AR/VR maintenance: High throughput (>100 Mbps), low latency")
print()

print("="*70)
print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*70)
