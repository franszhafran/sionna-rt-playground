# Quick Start Guide

## Step-by-Step Setup (macOS)

### 1. Install LLVM (One-time setup)

Run the setup helper script:
```bash
chmod +x setup_llvm.sh
./setup_llvm.sh
```

This script will:
- Detect your Mac architecture (Apple Silicon or Intel)
- Check if LLVM is installed
- Optionally install LLVM for you (takes 30-60 minutes)
- Configure the environment variable automatically

**OR** install manually:
```bash
# Install LLVM
brew install --build-from-source llvm

# Add to your ~/.zshrc:
# For Apple Silicon (M1/M2/M3):
echo 'export DRJIT_LIBLLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"' >> ~/.zshrc

# For Intel Mac:
echo 'export DRJIT_LIBLLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"' >> ~/.zshrc

# Reload shell config
source ~/.zshrc
```

### 2. Set Up Python Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies (already done if following from main setup)
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Run the Simulation

```bash
# Easy way (with auto LLVM detection):
./run.sh

# OR manually:
source venv/bin/activate
python sionna_beamforming_sim.py
```

## Expected Output

The simulation will:
1. Load the 3D scene (simple_street_canyon)
2. Configure 2 gNBs with 8x8 antenna arrays
3. Configure 8 UEs with 2x2 antenna arrays
4. Compute ray tracing paths with beamforming

You should see output like:
```
Sionna version: 2.0.1
PyTorch version: 2.11.0

[1/5] Setting up 3D scene...
  - Scene loaded: simple_street_canyon
  - Frequency: 3.5 GHz
  - Synthetic array enabled: True

[2/5] Configuring antenna arrays for beamforming...
  - gNB array: 8x8 URA (64 elements)
  - UE array: 2x2 URA (4 elements)

[3/5] Configuring 2 gNBs (base stations)...
  - gNB 1 added at position [0.0, 0.0, 30.0]
  - gNB 2 added at position [100.0, 50.0, 30.0]

[4/5] Configuring 8 UEs (user equipment)...
  - UE 1 added at position [20.0, 10.0, 1.5]
  ...

[5/5] Running beamforming and ray tracing simulation...
  - Computing propagation paths with ray tracing...
  - Ray tracing complete!

✓ Simulation setup complete!
```

## Troubleshooting

### Error: "LLVM backend is inactive"
- Make sure LLVM is installed: `ls /opt/homebrew/opt/llvm/lib/libLLVM.dylib`
- Check environment variable: `echo $DRJIT_LIBLLVM_PATH`
- Try the setup script: `./setup_llvm.sh`

### LLVM Installation Takes Forever
- Yes, compiling LLVM from source takes 30-60 minutes
- You can check progress: `brew info llvm`
- Make sure you have at least 10GB of free disk space

### Virtual Environment Issues
```bash
# Deactivate and recreate
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## What's Next?

After the simulation runs successfully, you can:

1. **Modify the configuration** in `sionna_beamforming_sim.py`:
   - Change gNB/UE positions
   - Adjust antenna array sizes
   - Modify ray tracing parameters

2. **Visualize the scene**:
   ```python
   scene.preview()  # Interactive 3D view
   ```

3. **Analyze the results**:
   - Access channel information via `paths` object
   - Compute beamforming weights
   - Calculate SINR and throughput

4. **Extend the simulation**:
   - Add UE mobility
   - Implement different beamforming algorithms
   - Test multi-user scenarios
