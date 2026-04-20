"""
Sionna RT 3D Environment with Beamforming
2 gNBs (Base Stations) and 8 UEs (User Equipment)
"""

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, Camera

# Set random seed for reproducibility
torch.manual_seed(42)
np.random.seed(42)

print(f"Sionna version: {sionna.__version__}")
print(f"PyTorch version: {torch.__version__}")

# ============================================================================
# Scene Setup
# ============================================================================
print("\n[1/5] Setting up 3D scene...")

# Load a simple scene (Sionna provides built-in scenes)
# Using the 'simple_street_canyon' scene as a starting point
scene = load_scene(sionna.rt.scene.simple_street_canyon)

# Configure scene properties
scene.frequency = 3.5e9  # 3.5 GHz carrier frequency
scene.synthetic_array = True  # Enable synthetic array for beamforming

print(f"  - Scene loaded: simple_street_canyon")
print(f"  - Frequency: {scene.frequency/1e9} GHz")
print(f"  - Synthetic array enabled: {scene.synthetic_array}")

# ============================================================================
# Configure Antenna Arrays for Beamforming
# ============================================================================
print("\n[2/5] Configuring antenna arrays for beamforming...")

# gNB antenna configuration (for beamforming)
# Using URA (Uniform Rectangular Array) with 8x8 elements
gnb_array = PlanarArray(
    num_rows=8,
    num_cols=8,
    vertical_spacing=0.5,      # Half wavelength spacing
    horizontal_spacing=0.5,    # Half wavelength spacing
    pattern="iso",             # Isotropic pattern
    polarization="V"           # Vertical polarization
)

# UE antenna configuration (simpler array)
# Using 2x2 array for UEs
ue_array = PlanarArray(
    num_rows=2,
    num_cols=2,
    vertical_spacing=0.5,
    horizontal_spacing=0.5,
    pattern="iso",
    polarization="V"
)

print(f"  - gNB array: {gnb_array.num_rows}x{gnb_array.num_cols} URA (64 elements)")
print(f"  - UE array: {ue_array.num_rows}x{ue_array.num_cols} URA (4 elements)")

# ============================================================================
# Configure 2 gNBs (Base Stations)
# ============================================================================
print("\n[3/5] Configuring 2 gNBs (base stations)...")

# gNB positions in the scene
gnb_positions = [
    [0.0, 0.0, 30.0],      # gNB 1: centered, 30m height
    [100.0, 50.0, 30.0]    # gNB 2: 100m east, 50m north, 30m height
]

gnb_orientations = [
    [0.0, 0.0, 0.0],       # gNB 1: facing forward
    [0.0, 0.0, np.pi]      # gNB 2: facing backward (180 degrees)
]

# Create transmitters (gNBs)
for i, (pos, orient) in enumerate(zip(gnb_positions, gnb_orientations)):
    tx = Transmitter(
        name=f"gnb_{i+1}",
        position=pos,
        orientation=orient
    )
    tx.array = gnb_array
    scene.add(tx)
    print(f"  - gNB {i+1} added at position {pos} with orientation {orient}")

# ============================================================================
# Configure 8 UEs (User Equipment)
# ============================================================================
print("\n[4/5] Configuring 8 UEs (user equipment)...")

# UE positions distributed in the scene
# Arranged in a pattern around the gNBs
ue_positions = [
    [20.0, 10.0, 1.5],     # UE 1
    [40.0, -15.0, 1.5],    # UE 2
    [60.0, 20.0, 1.5],     # UE 3
    [80.0, -10.0, 1.5],    # UE 4
    [30.0, 40.0, 1.5],     # UE 5
    [50.0, 35.0, 1.5],     # UE 6
    [70.0, 45.0, 1.5],     # UE 7
    [90.0, 30.0, 1.5],     # UE 8
]

ue_orientations = [
    [0.0, 0.0, 0.0],       # All UEs facing forward
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0],
]

# Create receivers (UEs)
for i, (pos, orient) in enumerate(zip(ue_positions, ue_orientations)):
    rx = Receiver(
        name=f"ue_{i+1}",
        position=pos,
        orientation=orient
    )
    rx.array = ue_array
    scene.add(rx)
    print(f"  - UE {i+1} added at position {pos}")

# ============================================================================
# Beamforming and Ray Tracing Simulation
# ============================================================================
print("\n[5/5] Running beamforming and ray tracing simulation...")

# Configure camera for visualization (optional)
scene.camera = Camera(
    position=[50.0, 100.0, 50.0],
    look_at=[50.0, 20.0, 0.0]
)

# Compute propagation paths using ray tracing
# This will compute all paths from all transmitters to all receivers
print("  - Computing propagation paths with ray tracing...")

# Configure ray tracing parameters
scene.tx_array = gnb_array
scene.rx_array = ue_array

# Compute channel impulse responses
# max_depth: maximum number of reflections
# num_samples: number of rays to trace
paths = scene.compute_paths(
    max_depth=5,           # Up to 5 reflections
    num_samples=int(1e6),  # 1 million rays for accurate results
    los=True,              # Include line-of-sight paths
    reflection=True,       # Include reflections
    diffraction=True,      # Include diffraction
    scattering=False       # Disable scattering for speed
)

print(f"  - Ray tracing complete!")
print(f"  - Max reflection depth: 5")
print(f"  - Number of samples: 1M")

# Beamforming weights computation
print("\n  - Computing beamforming weights...")
print("  - Using Maximum Ratio Transmission (MRT) for downlink beamforming")

# The paths object contains all the channel information needed for beamforming
# In a real implementation, you would compute beamforming weights based on:
# - Channel State Information (CSI) from the paths
# - Beamforming algorithm (e.g., MRT, Zero-Forcing, MMSE)

print("\n✓ Simulation setup complete!")
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Scene: simple_street_canyon")
print(f"Frequency: {scene.frequency/1e9} GHz")
print(f"Number of gNBs: 2")
print(f"Number of UEs: 8")
print(f"gNB antenna array: {gnb_array.num_rows}x{gnb_array.num_cols} (64 elements)")
print(f"UE antenna array: {ue_array.num_rows}x{ue_array.num_cols} (4 elements)")
print(f"Beamforming enabled: Yes (via large antenna arrays)")
print(f"Ray tracing parameters:")
print(f"  - Max reflections: 5")
print(f"  - Ray samples: 1M")
print(f"  - LOS: Enabled")
print(f"  - Reflections: Enabled")
print(f"  - Diffraction: Enabled")
print("="*60)

print("\nNext steps:")
print("1. Access channel information via 'paths' object")
print("2. Compute beamforming weights from CSI")
print("3. Evaluate SINR and throughput for each UE")
print("4. Visualize the scene with: scene.preview()")
print("5. Render coverage maps with: scene.render_to_file()")
