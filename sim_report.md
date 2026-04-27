# Car Factory 5G Simulation Report

**Channel model:** Ray Tracing (Sionna RT, max depth 3)  
**Beamforming:** MMSE (per-RB, 51 resource blocks)  
**Frequency:** 3.80 GHz  
**OFDM:** μ=1, 30 kHz SCS, 51 RBs, 612 active subcarriers, BW ≈ 18.36 MHz, CP eff = 0.9333  
**Run on:** `ma012@lkc` — `/home/ma012/sionna-rt-playground`

---

## Factory Layout

Total area: **250 m × 160 m**, 4 buildings, open yard between them.  
General Assembly is divided into **4 sections** by 3 internal partition walls with pass-through doors.

| Building | Dimensions (W×L×H) | x-range | y-range | Sections | gNBs |
|---|---|---|---|---|---|
| Stamping Plant | 75 × 80 × 12 m | 5 – 80 m | 5 – 85 m | 1 | 2 |
| Body Shop | 105 × 85 × 10 m | 95 – 200 m | 5 – 90 m | 1 | 3 |
| Paint Shop | 35 × 70 × 9 m | 210 – 245 m | 5 – 75 m | 1 | 2 |
| General Assembly | 240 × 55 × 10 m | 5 – 245 m | 100 – 155 m | 4 (Chassis / Powertrain / Trim / Final QC) | 4 |

### Internal Partition Walls (General Assembly)

| Wall | x (m) | y-span (m) | Door center |
|---|---|---|---|
| Chassis / Powertrain | 65 | 100 – 155 | y = 120 m |
| Powertrain / Trim | 125 | 100 – 155 | y = 130 m |
| Trim / Final QC | 185 | 100 – 155 | y = 140 m |

### gNB Placement (11 total, ceiling-mounted)

| gNB | x (m) | y (m) | z (m) | Building / Section |
|---|---|---|---|---|
| gNB-0 | 27.0 | 30.0 | 11.5 | Stamping Plant |
| gNB-1 | 57.0 | 60.0 | 11.5 | Stamping Plant |
| gNB-2 | 120.0 | 35.0 | 9.5 | Body Shop |
| gNB-3 | 147.0 | 55.0 | 9.5 | Body Shop |
| gNB-4 | 175.0 | 75.0 | 9.5 | Body Shop |
| gNB-5 | 227.0 | 25.0 | 8.5 | Paint Shop |
| gNB-6 | 227.0 | 58.0 | 8.5 | Paint Shop |
| gNB-7 | 35.0 | 127.0 | 9.5 | General Assembly — Chassis |
| gNB-8 | 95.0 | 127.0 | 9.5 | General Assembly — Powertrain |
| gNB-9 | 155.0 | 127.0 | 9.5 | General Assembly — Trim |
| gNB-10 | 215.0 | 127.0 | 9.5 | General Assembly — Final QC |

All gNBs use a **4×4 planar array** (16 antenna elements, half-wavelength spacing, vertical polarization).

---

## UE Setup

**400 UEs total**, distributed across buildings with a fixed random seed (reproducible).  
Each UE uses a **1×1 single-element** antenna, placed 0.25 – 3.0 m above floor level.

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
| Avg SINR | -8.15 dB |
| Avg Throughput per UE | 7.60 Mbps |
| Total Throughput | 3,038.81 Mbps |
| Avg Latency | 0.5001 ms |
| Max Latency | 0.5002 ms |
| **Overall SLA Pass Rate** | **48.8% (195 / 400)** |

> All latency figures are dominated by the 0.5 ms 5G NR slot duration (30 kHz SCS). Propagation delays across the factory are sub-microsecond and never become a binding constraint. Every failure is purely throughput-limited.

### QoS / SLA Results by UE Type

| UE Type | Req Lat (ms) | Req Tput (Mbps) | Total | Pass | Fail | Pass Rate |
|---|---|---|---|---|---|---|
| safety_sensor | 2.0 | 0.1 | 61 | 61 | 0 | **100.0%** |
| robotic_arm | 5.0 | 1.0 | 118 | 112 | 6 | **94.9%** |
| agv | 10.0 | 5.0 | 65 | 11 | 54 | **16.9%** |
| worker_tablet | 100.0 | 10.0 | 80 | 8 | 72 | **10.0%** |
| vision_camera | 50.0 | 50.0 | 76 | 3 | 73 | **3.9%** |
| **TOTAL** | — | — | **400** | **195** | **205** | **48.8%** |

### Failure Analysis

All 205 failures are throughput failures (`tput < X Mbps`). No UE misses its latency target.

**vision_camera (3.9% pass, 73 fail):** The 50 Mbps requirement is extremely demanding for a single-antenna UE. Only 3 UEs happen to be in near-LOS proximity to a gNB with sufficient SINR (e.g., UE-311 at +8 dB / 51 Mbps via gNB-7). The rest sit at −6 to −18 dB, yielding 1–6 Mbps.

**worker_tablet (10.0% pass, 72 fail):** Assembly hall UEs are spread over 240 m in 4 sections separated by concrete walls. Only 8 of 80 are close enough to their section gNB for ≥10 Mbps. SINR across the hall averages around −10 dB.

**agv (16.9% pass, 54 fail):** AGVs require 5 Mbps. Only 11 of 65 pass — those near-LOS to a gNB (e.g., UE-367 at +12 dB / 70 Mbps, UE-378 at +13.5 dB / 78 Mbps). The majority sit at −8 to −12 dB with 2–4 Mbps.

**robotic_arm (94.9% pass, 6 fail):** The 1 Mbps floor is achievable even at −12 to −13 dB SINR. Only 6 extreme outliers (≤−13 dB, heavily shadowed corners) fall below threshold.

**safety_sensor (100.0% pass):** The 0.1 Mbps requirement is met by every UE — even the weakest link (−14 dB) still delivers ~1 Mbps, well above the threshold.

---

## Observations

1. **SINR remains the bottleneck.** Average −8.15 dB reflects a dense, reflective concrete indoor environment with internal partition walls adding additional multipath. The new partition walls slightly reduced average SINR vs. the previous open-floor layout (−8.15 dB vs. −7.62 dB), dropping the overall pass rate from 52.5% → 48.8%.

2. **Partition walls help section isolation but increase interference.** Each Assembly section now has its own dedicated gNB (gNB-7 to gNB-10), reducing inter-section interference. However, reflections off the concrete dividers increase intra-section multipath, explaining the SINR drop in that zone.

3. **Vision cameras need rethinking.** A 50 Mbps single-UE requirement is unreachable without dedicated near-LOS gNB coverage. Consider collocating cameras directly beneath gNBs or using wired backhaul for fixed camera positions.

4. **Assembly hall remains the weak zone.** Despite 4 dedicated gNBs, the 240 m × 55 m hall with 173 UEs is still the hardest area to serve. Higher-gain arrays (8×8 instead of 4×4) or denser deployment would significantly lift worker_tablet and AGV pass rates.

5. **Safety-critical devices are fine.** All 61 safety sensors pass 100%, validating the 5G network for safety telemetry under all propagation conditions.

6. **Latency is not a concern.** At factory scale, propagation delay is negligible. The 0.5 ms slot latency is well inside every QoS budget, including the tightest (2 ms for safety sensors).
