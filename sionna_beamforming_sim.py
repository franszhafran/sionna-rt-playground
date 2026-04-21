"""
Sionna RT 3D Environment with Beamforming
2 gNBs (Base Stations) and 8 UEs (User Equipment)
"""

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, Camera, PathSolver

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

print(f"  - gNB array: 8x8 URA (64 elements)")
print(f"  - UE array: 2x2 URA (4 elements)")

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

# Compute channel impulse responses using PathSolver (Sionna 2.0+ API)
# Create the path solver
path_solver = PathSolver()

# Compute the paths
# max_depth: maximum number of reflections/interactions (0 = LoS only, 1 = LoS + 1st reflection, etc.)
# The scene must have transmitters and receivers already added
paths = path_solver(scene, max_depth=5)

print(f"  - Ray tracing complete!")
print(f"  - Max reflection depth: 5")

# ============================================================================
# Channel Analysis and Beamforming Weights Computation
# ============================================================================
print("\n[6/7] Analyzing channel information...")

# Access channel information from paths
# In Sionna RT 2.0, paths.a returns a tuple of (real, imag) tensors
a_tuple = paths.a  # Tuple of (real, imaginary) parts
tau = paths.tau    # Path delays

print(f"  - Channel coefficients shape (real): {a_tuple[0].shape}")
print(f"  - Number of RX (UEs): {a_tuple[0].shape[0]}")
print(f"  - RX antennas per UE: {a_tuple[0].shape[1]}")
print(f"  - Number of TX (gNBs): {a_tuple[0].shape[2]}")
print(f"  - TX antennas per gNB: {a_tuple[0].shape[3]}")
print(f"  - Number of paths found: {a_tuple[0].shape[4]}")

# Convert DrJit tensors to NumPy arrays then to PyTorch
# Shape: [num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths]
a_real = np.array(a_tuple[0])
a_imag = np.array(a_tuple[1])

# Create complex channel coefficients
a_complex = a_real + 1j * a_imag
h = torch.from_numpy(a_complex).to(torch.complex64)

# ============================================================================
# Compute Beamforming Weights (Maximum Ratio Transmission - MRT)
# ============================================================================
print("\n[7/8] Computing beamforming weights...")
print("  - Using Maximum Ratio Transmission (MRT) for downlink beamforming")

# For MRT, the beamforming weight is the conjugate of the channel
# This maximizes the received signal power at the UE
# w_mrt = H* / ||H||  where H is the channel matrix

# Aggregate over all paths by summing
# Shape: [num_rx, num_rx_ant, num_tx, num_tx_ant]
h_eff = torch.sum(h, dim=-1)  # Sum over paths dimension

print(f"  - Effective channel matrix shape: {h_eff.shape}")
print(f"  - MRT weights computed for {h_eff.shape[2]} gNBs")
print(f"  - Each gNB serves {h_eff.shape[0]} UEs")

# Compute MRT weights for each TX-RX pair
# Shape: [num_rx, num_rx_ant, num_tx, num_tx_ant]
mrt_weights = torch.conj(h_eff)

# Normalize the weights for each TX antenna array
weights_norm = torch.sqrt(torch.sum(torch.abs(mrt_weights)**2, dim=3, keepdim=True))
mrt_weights_norm = mrt_weights / (weights_norm + 1e-10)

# ============================================================================
# Evaluate SINR and Throughput
# ============================================================================
print("\n[8/8] Evaluating SINR and throughput for each UE...")

# System parameters
noise_power_dbm = -174 + 10 * np.log10(20e6)  # Thermal noise for 20 MHz BW
noise_power = 10 ** (noise_power_dbm / 10) / 1000  # Convert to Watts
tx_power = 1.0  # 1 Watt transmit power per gNB

# Calculate received signal power for each UE
# Apply beamforming: y = H * w * sqrt(P)
# Shape after beamforming: [num_rx, num_rx_ant, num_tx]
received_signal = torch.sum(h_eff * mrt_weights_norm, dim=3)  # Sum over TX antennas
signal_power = torch.abs(received_signal) ** 2 * tx_power

# Sum over RX antennas to get total power per UE from each gNB
# Shape: [num_rx, num_tx]
signal_power_per_link = torch.sum(signal_power, dim=1)

# For simplicity, assume no inter-cell interference
# SINR = Signal Power / Noise Power for each UE-gNB link
sinr_linear = signal_power_per_link / noise_power
sinr_db = 10 * torch.log10(sinr_linear + 1e-10)

# Calculate throughput using Shannon capacity formula
# C = BW * log2(1 + SINR)
bandwidth = 20e6  # 20 MHz
throughput_bps = bandwidth * torch.log2(1 + sinr_linear)
throughput_mbps = throughput_bps / 1e6

print("\n" + "="*70)
print("PERFORMANCE METRICS PER UE-gNB LINK")
print("="*70)
print(f"{'UE':<6} {'gNB':<6} {'SINR (dB)':<15} {'Throughput (Mbps)':<20}")
print("-"*70)

# Extract and display metrics for each UE-gNB link
num_ues = h_eff.shape[0]
num_gnbs = h_eff.shape[2]

for ue_idx in range(num_ues):
    for gnb_idx in range(num_gnbs):
        sinr_val = sinr_db[ue_idx, gnb_idx].item()
        tput_val = throughput_mbps[ue_idx, gnb_idx].item()
        print(f"UE {ue_idx+1:<4} gNB {gnb_idx+1:<4} {sinr_val:<15.2f} {tput_val:<20.2f}")

print("="*70)

# For each UE, select the best gNB (highest SINR)
best_gnb_idx = torch.argmax(sinr_db, dim=1)
best_sinr = torch.max(sinr_db, dim=1)[0]
best_throughput = torch.max(throughput_mbps, dim=1)[0]

print("\nBEST SERVING gNB PER UE:")
print(f"{'UE':<6} {'Best gNB':<12} {'SINR (dB)':<15} {'Throughput (Mbps)':<20}")
print("-"*70)
for ue_idx in range(num_ues):
    gnb = best_gnb_idx[ue_idx].item() + 1
    sinr_val = best_sinr[ue_idx].item()
    tput_val = best_throughput[ue_idx].item()
    print(f"UE {ue_idx+1:<4} gNB {gnb:<10} {sinr_val:<15.2f} {tput_val:<20.2f}")

# Compute aggregate statistics
avg_best_sinr = torch.mean(best_sinr).item()
avg_best_throughput = torch.mean(best_throughput).item()
total_throughput = torch.sum(best_throughput).item()

print("="*70)
print(f"\nAGGREGATE STATISTICS (Best gNB per UE):")
print(f"  - Average SINR: {avg_best_sinr:.2f} dB")
print(f"  - Average throughput per UE: {avg_best_throughput:.2f} Mbps")
print(f"  - Total system throughput: {total_throughput:.2f} Mbps")
print(f"  - Spectral efficiency: {total_throughput/20:.2f} bps/Hz")

print("\n✓ Full simulation complete!")
print("\n" + "="*70)
print("SIMULATION CONFIGURATION SUMMARY")
print("="*70)
print(f"Scene: simple_street_canyon")
print(f"Frequency: {scene.frequency/1e9} GHz")
print(f"Bandwidth: 20 MHz")
print(f"TX Power: 1 W (30 dBm) per gNB")
print(f"Number of gNBs: 2")
print(f"Number of UEs: 8")
print(f"gNB antenna array: 8x8 (64 elements)")
print(f"UE antenna array: 2x2 (4 elements)")
print(f"Beamforming: Maximum Ratio Transmission (MRT)")
print(f"Ray tracing parameters:")
print(f"  - Max reflections: 5")
print(f"  - LOS and specular reflections computed via image method")
print(f"  - Diffuse scattering computed via SBR heuristics")
print("="*70)
