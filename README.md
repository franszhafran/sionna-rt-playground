# Sionna RT: 3D Beamforming Simulation

This repository contains a Sionna Ray Tracing simulation with beamforming capabilities, featuring 2 gNBs (base stations) and 8 UEs (user equipment) in a 3D environment.

## Features

- **3D Ray Tracing Environment**: Using Sionna RT with the simple_street_canyon scene
- **2 gNBs**: Base stations equipped with 8x8 URA (64 antenna elements)
- **8 UEs**: User equipment with 2x2 URA (4 antenna elements)
- **Beamforming**: Enabled through large antenna arrays for MRT/ZF algorithms
- **Frequency**: 3.5 GHz carrier frequency
- **Ray Tracing**: Up to 5 reflections with 1M ray samples

## Setup

### Prerequisites

- Python 3.11 or higher
- macOS (tested) / Ubuntu 24.04 (recommended)
- **LLVM** (required for Sionna RT on CPU)

### Installation

1. **Install LLVM** (required for ray tracing):

   **On macOS:**
   ```bash
   # This will compile LLVM from source (may take 30-60 minutes)
   brew install --build-from-source llvm

   # After installation, set the environment variable
   # For Apple Silicon:
   export DRJIT_LIBLLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"

   # For Intel Mac:
   export DRJIT_LIBLLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"
   ```

   **On Ubuntu:**
   ```bash
   sudo apt-get update
   sudo apt-get install llvm
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

   Alternatively, install Sionna directly:
   ```bash
   pip install sionna
   ```

### Important: LLVM Setup

Sionna RT requires LLVM for CPU-based ray tracing. If you encounter the error:
```
ImportError: jit_init_thread_state(): the LLVM backend is inactive because the LLVM shared library ("libLLVM.dylib") could not be found!
```

Make sure to:
1. Install LLVM using the instructions above
2. Set the `DRJIT_LIBLLVM_PATH` environment variable
3. Add the export command to your shell profile (~/.zshrc or ~/.bashrc) to make it persistent

You can add this to your shell profile:
```bash
# Add to ~/.zshrc (macOS default) or ~/.bashrc
export DRJIT_LIBLLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"  # Apple Silicon
# OR
export DRJIT_LIBLLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"     # Intel Mac
```

## Running the Simulation

Activate the virtual environment and run the simulation:

```bash
source venv/bin/activate
python sionna_beamforming_sim.py
```

## Configuration

### gNB Configuration
- **Position 1**: [0.0, 0.0, 30.0] - centered, 30m height
- **Position 2**: [100.0, 50.0, 30.0] - 100m east, 50m north, 30m height
- **Antenna Array**: 8x8 URA (64 elements)
- **Spacing**: Half-wavelength (0.5λ)

### UE Configuration
- **8 UEs** distributed in the scene at 1.5m height
- **Antenna Array**: 2x2 URA (4 elements)
- **Spacing**: Half-wavelength (0.5λ)

### Ray Tracing Parameters
- **Max reflection depth**: 5
- **Number of samples**: 1M rays
- **LOS**: Enabled
- **Reflections**: Enabled
- **Diffraction**: Enabled
- **Scattering**: Disabled (for speed)

## Next Steps

The simulation sets up the environment and computes propagation paths. You can extend it by:

1. **Compute Beamforming Weights**: Use CSI from paths to calculate MRT/ZF weights
2. **Evaluate Performance**: Calculate SINR, throughput, and spectral efficiency
3. **Visualization**:
   - `scene.preview()` - Interactive 3D visualization
   - `scene.render_to_file()` - Generate coverage maps
4. **Add Mobility**: Implement UE movement scenarios
5. **Multi-user MIMO**: Test different beamforming algorithms

## Documentation

- [Sionna Documentation](https://nvlabs.github.io/sionna/)
- [Sionna RT Tutorial](https://nvlabs.github.io/sionna/examples/Sionna_RT_Introduction.html)
- [Installation Guide](https://nvlabs.github.io/sionna/installation.html)

## Architecture

```
gNB 1 (0,0,30m)              gNB 2 (100,50,30m)
    |                             |
    |-- 8x8 Antenna Array        |-- 8x8 Antenna Array
    |                             |
    +-------- Ray Tracing --------+
                  |
         +--------+--------+
         |                 |
    UE 1-4           UE 5-8
    (2x2 arrays)     (2x2 arrays)
```

## License

This project uses Sionna, which is licensed under Apache 2.0.
