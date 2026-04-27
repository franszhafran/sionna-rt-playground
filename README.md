# Sionna RT: Car Factory 5G Simulation

Indoor 5G NR simulation of a 250 m × 160 m car factory using Sionna Ray Tracing, with MMSE/MRT beamforming, per-device QoS SLA tracking, and a browser-based 3D walkthrough.

## File Overview

| File | What it does |
|------|-------------|
| `factory_layout.py` | **Scene generator.** Defines 4 factory buildings, places 10 ceiling-mounted gNBs and ~400 UEs (5 device types, fixed random seed). Writes PLY meshes, `car_factory_scene/car_factory.xml`, and `config.json`. Run this first. |
| `factory_sim.py` | **Main simulation.** Loads `config.json`, runs ray-tracing (Sionna `PathSolver`) or statistical 3GPP InF-SH channel, computes MMSE or MRT beamforming, then prints per-UE SINR/throughput/latency and QoS SLA pass/fail by device type. |
| `factory_viewer.py` | **3D browser viewer.** Merges PLY meshes into OBJ, injects gNB/UE markers from `config.json`, generates a Three.js first-person walkthrough (WASD + mouse), and serves it on `http://localhost:8889`. |
| `config.json` | **Runtime config.** Frequency (3.8 GHz), beamforming method, channel model toggle, antenna array sizes, and all gNB/UE positions. Auto-updated by `factory_layout.py`. |
| `config_schema.py` | **Pydantic schema.** Validates `config.json` at load time. |
| `factory_preview.ipynb` | **Notebook.** Interactive Sionna scene preview. |
| `car_factory_scene/` | **Generated assets.** Mitsuba XML scene, PLY mesh files, and viewer HTML/OBJ (created by the scripts above). |

## Factory Layout

```
250 m × 160 m  —  4 buildings  —  10 gNBs  —  ~400 UEs

  Stamping Plant   (75×80 m, h=12 m)  —  2 gNBs,  78 UEs
  Body Shop       (105×85 m, h=10 m)  —  3 gNBs, 117 UEs
  Paint Shop       (35×70 m, h= 9 m)  —  2 gNBs,  32 UEs
  General Assembly(240×55 m, h=10 m)  —  3 gNBs, 173 UEs
```

UE types: `agv`, `robotic_arm`, `vision_camera`, `safety_sensor`, `worker_tablet` — each with its own latency/throughput QoS requirement.

## Quick Start

### Prerequisites

- Python 3.11+
- LLVM (required by Sionna RT on CPU)

**macOS:**
```bash
brew install --build-from-source llvm
export DRJIT_LIBLLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"  # Apple Silicon
# export DRJIT_LIBLLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"   # Intel
```

**Ubuntu:**
```bash
sudo apt-get install llvm
```

### Install

```bash
python3 -m venv venv && source venv/bin/activate
pip install sionna
```

### Run

```bash
# 1. Generate scene + config
python factory_layout.py

# 2. Run simulation (ray tracing or statistical channel)
python factory_sim.py

# 3. Launch 3D browser viewer
python factory_viewer.py          # http://localhost:8889
python factory_viewer.py --port 9000
```

## Configuration

Edit `config.json` (or re-run `factory_layout.py` to regenerate it):

| Key | Default | Description |
|-----|---------|-------------|
| `frequency` | 3.8e9 | Carrier frequency (Hz) |
| `max_depth` | 3 | Ray reflection depth |
| `beamforming_method` | `"MMSE"` | `"MMSE"` or `"MRT"` |
| `use_statistical_channel` | `false` | `true` = fast 3GPP InF-SH model, `false` = full ray tracing |
| `tx_array` | 4×4 | gNB antenna array (16 elements) |
| `rx_array` | 1×1 | UE antenna (single element) |

> Set `use_statistical_channel: true` for fast iteration — ray tracing on a 250×160 m scene is slow.

## Documentation

- [Sionna Documentation](https://nvlabs.github.io/sionna/)
- [Sionna RT Tutorial](https://nvlabs.github.io/sionna/examples/Sionna_RT_Introduction.html)

## License

Uses Sionna (Apache 2.0).
