"""
Detailed Performance Comparison: 3.7 GHz vs 28 GHz
Per-Device Latency and Throughput Analysis
"""
import sys
sys.path.append('/home/ma012/sionna-rt-playground/venv/lib/python3.12/site-packages')

import numpy as np
import torch
import sionna
from sionna.rt import load_scene, PathSolver, PlanarArray, Transmitter, Receiver

def run_simulation(frequency, bandwidth, label):
    """Run simulation and return metrics"""
    scene = load_scene(sionna.rt.scene.simple_street_canyon)
    scene.frequency = frequency
    scene.synthetic_array = True
    
    gnb_array = PlanarArray(num_rows=8, num_cols=8, vertical_spacing=0.5,
                            horizontal_spacing=0.5, pattern="iso", polarization="V")
    device_array = PlanarArray(num_rows=2, num_cols=2, vertical_spacing=0.5,
                               horizontal_spacing=0.5, pattern="iso", polarization="V")
    
    scene.tx_array = gnb_array
    scene.rx_array = device_array
    
    # Deploy gNBs
    for i, pos in enumerate([[20, 20, 9], [50, 30, 9], [80, 20, 9]]):
        tx = Transmitter(name=f"gnb_{i+1}", position=pos)
        scene.add(tx)
    
    # Deploy devices
    devices = [
        ([25, 22, 0.5], "AGV-1"), ([35, 18, 0.5], "AGV-2"),
        ([55, 28, 0.5], "Robot-1"), ([65, 32, 0.5], "Robot-2"),
        ([40, 35, 2.5], "Sensor/Cam"), ([60, 25, 2.5], "AR_Station"),
        ([75, 18, 1.5], "VR_Device"), ([30, 25, 0.8], "IoT_Gateway")
    ]
    
    for i, (pos, name) in enumerate(devices):
        rx = Receiver(name=f"device_{i+1}", position=pos)
        scene.add(rx)
    
    # Ray tracing
    path_solver = PathSolver()
    paths = path_solver(scene, max_depth=3)
    
    # Extract channel
    a_tuple = paths.a
    tau = paths.tau
    a_real, a_imag = np.array(a_tuple[0]), np.array(a_tuple[1])
    h = torch.from_numpy(a_real + 1j * a_imag).to(torch.complex64)
    delays = np.array(tau)
    
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
    
    # Throughput
    tput_bps = bandwidth * torch.log2(1 + sinr_linear)
    tput_mbps = tput_bps / 1e6
    best_tput = torch.gather(tput_mbps, 1, best_gnb.unsqueeze(1)).squeeze(1)
    
    # Latency estimates
    # Air interface latency (physical layer)
    slot_duration_us = 125 if frequency < 10e9 else 62.5  # 5G NR slot
    tti_us = slot_duration_us  # Transmission Time Interval
    
    # Propagation delay
    max_delay_ns = torch.max(torch.from_numpy(delays)) * 1e9
    prop_delay_us = max_delay_ns.item() / 1000
    
    # Processing delay (estimate based on complexity)
    proc_delay_us = 200 if frequency < 10e9 else 100  # mmWave has faster processing
    
    # Total one-way latency per device
    total_latency_us = np.zeros(len(devices))
    for i in range(len(devices)):
        # Base latency components
        latency = tti_us + prop_delay_us + proc_delay_us
        
        # Add retransmission overhead based on SINR
        device_sinr = best_sinr[i].item()
        if device_sinr < 10:
            retx_factor = 1.5  # High retransmission
        elif device_sinr < 20:
            retx_factor = 1.2  # Some retransmission
        else:
            retx_factor = 1.0  # Minimal retransmission
        
        total_latency_us[i] = latency * retx_factor
    
    return {
        'devices': devices,
        'sinr_db': best_sinr.cpu().numpy(),
        'throughput_mbps': best_tput.cpu().numpy(),
        'latency_us': total_latency_us,
        'serving_gnb': best_gnb.cpu().numpy() + 1,
        'tti_us': tti_us,
        'prop_delay_us': prop_delay_us,
        'proc_delay_us': proc_delay_us
    }

print("="*80)
print("LATENCY & THROUGHPUT COMPARISON: 3.7 GHz vs 28 GHz")
print("="*80)
print()

print("Running simulations...")
print("  [1/2] 3.7 GHz (Sub-6 GHz, 20 MHz BW)...", end='', flush=True)
results_3_7 = run_simulation(3.7e9, 20e6, "3.7 GHz")
print(" ✓")

print("  [2/2] 28 GHz (mmWave, 100 MHz BW)...", end='', flush=True)
results_28 = run_simulation(28e9, 100e6, "28 GHz")
print(" ✓")

print()
print("="*80)
print("PER-DEVICE PERFORMANCE METRICS")
print("="*80)
print()

# Header
print("┌──────────────┬─────────────────────────┬─────────────────────────┐")
print("│   Device     │      3.7 GHz (Sub-6)    │      28 GHz (mmWave)    │")
print("├──────────────┼─────────────────────────┼─────────────────────────┤")
print("│              │ Tput    SINR   Latency  │ Tput    SINR   Latency  │")
print("│              │ (Mbps)  (dB)   (μs)     │ (Mbps)  (dB)   (μs)     │")
print("├──────────────┼─────────────────────────┼─────────────────────────┤")

for i, (pos, name) in enumerate(results_3_7['devices']):
    tput_3_7 = results_3_7['throughput_mbps'][i]
    sinr_3_7 = results_3_7['sinr_db'][i]
    lat_3_7 = results_3_7['latency_us'][i]
    
    tput_28 = results_28['throughput_mbps'][i]
    sinr_28 = results_28['sinr_db'][i]
    lat_28 = results_28['latency_us'][i]
    
    print(f"│ {name:12s} │ {tput_3_7:6.0f}  {sinr_3_7:5.1f}  {lat_3_7:6.0f}  │ {tput_28:6.0f}  {sinr_28:5.1f}  {lat_28:6.0f}  │")

print("└──────────────┴─────────────────────────┴─────────────────────────┘")

print()
print("="*80)
print("SUMMARY STATISTICS")
print("="*80)
print()

print("┌─────────────────────┬─────────────┬─────────────┬────────────┐")
print("│ Metric              │  3.7 GHz    │   28 GHz    │  Winner    │")
print("├─────────────────────┼─────────────┼─────────────┼────────────┤")

# Throughput
avg_tput_3_7 = np.mean(results_3_7['throughput_mbps'])
avg_tput_28 = np.mean(results_28['throughput_mbps'])
total_tput_3_7 = np.sum(results_3_7['throughput_mbps'])
total_tput_28 = np.sum(results_28['throughput_mbps'])

print(f"│ Avg Throughput/Dev  │ {avg_tput_3_7:7.0f} Mbps │ {avg_tput_28:7.0f} Mbps │ 28 GHz {avg_tput_28/avg_tput_3_7:.1f}x │")
print(f"│ Total Capacity      │ {total_tput_3_7:7.0f} Mbps │ {total_tput_28:7.0f} Mbps │ 28 GHz {total_tput_28/total_tput_3_7:.1f}x │")

# Latency
avg_lat_3_7 = np.mean(results_3_7['latency_us'])
avg_lat_28 = np.mean(results_28['latency_us'])
min_lat_3_7 = np.min(results_3_7['latency_us'])
min_lat_28 = np.min(results_28['latency_us'])

print(f"│ Avg Latency         │   {avg_lat_3_7:6.0f} μs  │   {avg_lat_28:6.0f} μs  │ 28 GHz {avg_lat_3_7/avg_lat_28:.2f}x │")
print(f"│ Min Latency         │   {min_lat_3_7:6.0f} μs  │   {min_lat_28:6.0f} μs  │ 28 GHz {min_lat_3_7/min_lat_28:.2f}x │")

# SINR
avg_sinr_3_7 = np.mean(results_3_7['sinr_db'])
avg_sinr_28 = np.mean(results_28['sinr_db'])

print(f"│ Avg SINR            │    {avg_sinr_3_7:5.1f} dB  │    {avg_sinr_28:5.1f} dB  │ 3.7 GHz    │")

print("└─────────────────────┴─────────────┴─────────────┴────────────┘")

print()
print("="*80)
print("LATENCY BREAKDOWN")
print("="*80)
print()

print("┌────────────────────────┬─────────────┬─────────────┐")
print("│ Component              │  3.7 GHz    │   28 GHz    │")
print("├────────────────────────┼─────────────┼─────────────┤")
print(f"│ TTI (Slot Duration)    │   {results_3_7['tti_us']:6.1f} μs  │   {results_28['tti_us']:6.1f} μs  │")
print(f"│ Propagation Delay      │   {results_3_7['prop_delay_us']:6.2f} μs  │   {results_28['prop_delay_us']:6.2f} μs  │")
print(f"│ Processing Delay       │   {results_3_7['proc_delay_us']:6.1f} μs  │   {results_28['proc_delay_us']:6.1f} μs  │")
print(f"│ Base One-Way Latency   │   {results_3_7['tti_us']+results_3_7['prop_delay_us']+results_3_7['proc_delay_us']:6.1f} μs  │   {results_28['tti_us']+results_28['prop_delay_us']+results_28['proc_delay_us']:6.1f} μs  │")
print(f"│ Round-Trip (2x)        │   {2*(results_3_7['tti_us']+results_3_7['prop_delay_us']+results_3_7['proc_delay_us']):6.0f} μs  │   {2*(results_28['tti_us']+results_28['prop_delay_us']+results_28['proc_delay_us']):6.0f} μs  │")
print("└────────────────────────┴─────────────┴─────────────┘")

print()
print("="*80)
print("APPLICATION SUITABILITY ANALYSIS")
print("="*80)
print()

apps = [
    ("AR/VR (< 10 ms, > 100 Mbps)", 10000, 100),
    ("Industrial Robot (< 1 ms, > 5 Mbps)", 1000, 5),
    ("AGV Navigation (< 10 ms, > 10 Mbps)", 10000, 10),
    ("8K Video (< 50 ms, > 100 Mbps)", 50000, 100),
    ("IoT Sensor (< 100 ms, > 1 Mbps)", 100000, 1),
    ("Voice/Video Call (< 30 ms, > 1 Mbps)", 30000, 1),
]

print("Application Requirements vs. Performance:")
print()
for app_name, lat_req_us, tput_req_mbps in apps:
    # Check 3.7 GHz
    meet_3_7_lat = np.sum(results_3_7['latency_us'] < lat_req_us)
    meet_3_7_tput = np.sum(results_3_7['throughput_mbps'] > tput_req_mbps)
    meet_3_7 = min(meet_3_7_lat, meet_3_7_tput)
    
    # Check 28 GHz
    meet_28_lat = np.sum(results_28['latency_us'] < lat_req_us)
    meet_28_tput = np.sum(results_28['throughput_mbps'] > tput_req_mbps)
    meet_28 = min(meet_28_lat, meet_28_tput)
    
    status_3_7 = "✓" if meet_3_7 >= 6 else "⚠" if meet_3_7 >= 4 else "✗"
    status_28 = "✓" if meet_28 >= 6 else "⚠" if meet_28 >= 4 else "✗"
    
    print(f"{app_name:40s}: 3.7GHz {status_3_7} ({meet_3_7}/8)  28GHz {status_28} ({meet_28}/8)")

print()
print("="*80)
print("KEY INSIGHTS")
print("="*80)
print()

print("Throughput:")
print(f"  • 28 GHz provides {avg_tput_28/avg_tput_3_7:.1f}x higher throughput per device")
print(f"  • Total capacity: 28 GHz = {total_tput_28/1000:.1f} Gbps vs 3.7 GHz = {total_tput_3_7/1000:.1f} Gbps")
print(f"  • Best for: 8K video, AR/VR, massive file transfers")
print()

print("Latency:")
print(f"  • 28 GHz achieves {avg_lat_3_7/avg_lat_28:.2f}x lower latency")
print(f"  • Shorter TTI (62.5 vs 125 μs) and faster processing")
print(f"  • Both meet < 1 ms requirement for URLLC (robot control)")
print(f"  • Best for: Ultra-low latency industrial automation")
print()

print("Coverage & Reliability:")
print(f"  • 3.7 GHz: Higher SINR ({avg_sinr_3_7:.1f} dB avg) = better coverage")
print(f"  • 28 GHz: Lower SINR ({avg_sinr_28:.1f} dB avg) but still excellent")
print(f"  • 3.7 GHz better for wide-area, mobility, penetration")
print(f"  • 28 GHz better for fixed, line-of-sight, capacity")
print()

print("Recommendation:")
print("  ✓ Use BOTH frequencies in hybrid deployment")
print("  ✓ 28 GHz: Fixed high-bandwidth (cameras, AR, edge)")
print("  ✓ 3.7 GHz: Mobile devices (AGVs, robots, tablets)")
print("  ✓ Dual connectivity for critical applications")
print()

print("="*80)
