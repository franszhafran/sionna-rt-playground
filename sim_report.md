# Car Factory 5G Simulation Report

**Channel model:** Ray Tracing (Sionna RT, max depth 3)  
**Beamforming:** MMSE  
**Frequency:** 3.80 GHz  
**Bandwidth:** 20 MHz  
**Run on:** `ma012@lkc` — `/home/ma012/sionna-rt-playground`

---

## Factory Layout

Total area: **250 m × 160 m**, 4 buildings, open yard between them.

| Building | Dimensions (W×L×H) | x-range | y-range | gNBs |
|---|---|---|---|---|
| Stamping Plant | 75 × 80 × 12 m | 5 – 80 m | 5 – 85 m | 2 |
| Body Shop | 105 × 85 × 10 m | 95 – 200 m | 5 – 90 m | 3 |
| Paint Shop | 35 × 70 × 9 m | 210 – 245 m | 5 – 75 m | 2 |
| General Assembly | 240 × 55 × 10 m | 5 – 245 m | 100 – 155 m | 3 |

### gNB Placement (10 total, ceiling-mounted)

| gNB | x (m) | y (m) | z (m) | Building |
|---|---|---|---|---|
| gNB-0 | 27.0 | 30.0 | 11.5 | Stamping Plant |
| gNB-1 | 57.0 | 60.0 | 11.5 | Stamping Plant |
| gNB-2 | 120.0 | 35.0 | 9.5 | Body Shop |
| gNB-3 | 147.0 | 55.0 | 9.5 | Body Shop |
| gNB-4 | 175.0 | 75.0 | 9.5 | Body Shop |
| gNB-5 | 227.0 | 25.0 | 8.5 | Paint Shop |
| gNB-6 | 227.0 | 58.0 | 8.5 | Paint Shop |
| gNB-7 | 65.0 | 127.0 | 9.5 | General Assembly |
| gNB-8 | 125.0 | 127.0 | 9.5 | General Assembly |
| gNB-9 | 195.0 | 127.0 | 9.5 | General Assembly |

All gNBs use a **4×4 planar array** (16 antenna elements, half-wavelength spacing, vertical polarization).

---

## UE Setup

**400 UEs total**, distributed across buildings with a fixed random seed (reproducible). Each UE uses a **1×1 single-element** antenna. UEs are placed 0.25 – 3.0 m above floor level, representing floor-level workstations and robots.

### UE Type Distribution

| UE Type | Count | Building Distribution |
|---|---|---|
| robotic_arm | 118 | 31 Stamping · 41 Body Shop · 11 Paint Shop · 35 Assembly |
| worker_tablet | 80 | 11 Stamping · 12 Body Shop · 5 Paint Shop · 52 Assembly |
| vision_camera | 76 | — · 23 Body Shop · 10 Paint Shop · 43 Assembly |
| agv | 65 | 16 Stamping · 23 Body Shop · — · 26 Assembly |
| safety_sensor | 61 | 20 Stamping · 18 Body Shop · 6 Paint Shop · 17 Assembly |

### QoS Requirements per UE Type

| UE Type | Max Latency | Min Throughput | Rationale |
|---|---|---|---|
| safety_sensor | 2 ms | 0.1 Mbps | Hard real-time safety alerts, tiny payload |
| robotic_arm | 5 ms | 1.0 Mbps | Low-latency control loop, modest data |
| agv | 10 ms | 5.0 Mbps | Navigation + sensor fusion, moderate bandwidth |
| worker_tablet | 100 ms | 10.0 Mbps | Human-facing app, higher bandwidth needed |
| vision_camera | 50 ms | 50.0 Mbps | HD video stream, bandwidth-intensive |

---

## Simulation Results

### Aggregate Metrics

| Metric | Value |
|---|---|
| Avg SINR | -7.62 dB |
| Avg Throughput per UE | 9.78 Mbps |
| Total Throughput | 3,912.93 Mbps |
| Avg Latency | 0.5001 ms |
| Max Latency | 0.5006 ms |
| **Overall SLA Pass Rate** | **52.5% (210 / 400)** |

> All latency figures are dominated by the 0.5 ms 5G NR slot duration (30 kHz SCS). Propagation delays across the factory are sub-microsecond and never become a binding constraint. Every failure is purely throughput-limited.

### QoS / SLA Results by UE Type

| UE Type | Req Lat (ms) | Req Tput (Mbps) | Total | Pass | Fail | Pass Rate |
|---|---|---|---|---|---|---|
| safety_sensor | 2.0 | 0.1 | 61 | 61 | 0 | **100.0%** |
| robotic_arm | 5.0 | 1.0 | 118 | 107 | 11 | **90.7%** |
| agv | 10.0 | 5.0 | 65 | 22 | 43 | **33.8%** |
| worker_tablet | 100.0 | 10.0 | 80 | 16 | 64 | **20.0%** |
| vision_camera | 50.0 | 50.0 | 76 | 4 | 72 | **5.3%** |
| **TOTAL** | — | — | **400** | **210** | **190** | **52.5%** |

### Failure Analysis

All 190 failures are throughput failures (`tput < X Mbps`). No UE misses its latency target.

**vision_camera (5.3% pass, 72 fail):** The 50 Mbps requirement is extremely demanding for a single-antenna UE. Only 4 UEs happen to be in near-LOS proximity to a gNB with enough SINR (e.g., UE-140 at 14.91 dB, UE-206 at 14.46 dB, UE-215 at 7.36 dB, UE-299 at 21.19 dB). The rest are deep in multipath shadow at –7 to –18 dB SINR.

**worker_tablet (20.0% pass, 64 fail):** Assembly hall UEs (gNB-7/8/9) are spread over 240 m in the same building. Many UEs sit far from any gNB, yielding –10 to –17 dB SINR. The 10 Mbps bar is met only by the 16 UEs that are either close to or in near-LOS of their serving gNB.

**agv (33.8% pass, 43 fail):** AGVs require 5 Mbps. Many are located in obstructed positions (behind walls, far ends of buildings). The 22 that pass tend to be centrally located or near a gNB.

**robotic_arm (90.7% pass, 11 fail):** The 1 Mbps floor is achievable even at –12 to –13 dB SINR. The 11 failures are extreme outliers at –15 to –20 dB (heavily shadowed corners or cross-building interference).

**safety_sensor (100.0% pass):** The 0.1 Mbps requirement is met by every UE in the deployment — even the weakest link at –18.36 dB still delivers ~0.42 Mbps, above the threshold.

---

## Observations

1. **SINR is the bottleneck.** Average –7.62 dB reflects a dense, reflective concrete indoor environment. More gNBs or higher-gain arrays (e.g., 8×8 instead of 4×4) would directly improve pass rates for bandwidth-hungry devices.

2. **Vision cameras need rethinking.** A 50 Mbps single-UE requirement is unreachable without dedicated near-LOS gNB coverage. Consider moving vision cameras closer to gNBs or using wired backhaul for fixed camera positions.

3. **Assembly hall is the weak zone.** gNB-7, -8, -9 cover 240 m × 55 m with 173 UEs — the largest and densest building. Adding 2 more gNBs here would significantly lift the worker_tablet and vision_camera pass rates.

4. **Safety-critical devices are fine.** All 61 safety sensors pass 100%, validating that the 5G network is sufficient for safety telemetry even under poor SINR.

5. **Latency is not a concern.** At factory scale, propagation delay is negligible. The 0.5 ms slot latency is well inside every QoS budget, including the tightest (2 ms for safety sensors).
