#!/bin/bash
# Run script for Sionna RT beamforming simulation

echo "Activating virtual environment..."
source venv/bin/activate

# Set LLVM path if not already set
if [ -z "$DRJIT_LIBLLVM_PATH" ]; then
    # Try to detect LLVM installation
    if [ -f "/opt/homebrew/opt/llvm/lib/libLLVM.dylib" ]; then
        export DRJIT_LIBLLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"
        echo "Using LLVM from: $DRJIT_LIBLLVM_PATH"
    elif [ -f "/usr/local/opt/llvm/lib/libLLVM.dylib" ]; then
        export DRJIT_LIBLLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"
        echo "Using LLVM from: $DRJIT_LIBLLVM_PATH"
    else
        echo "WARNING: LLVM not found!"
        echo "Please install LLVM with: brew install --build-from-source llvm"
        echo "Then set DRJIT_LIBLLVM_PATH environment variable"
        exit 1
    fi
fi

echo "Running Sionna RT beamforming simulation..."
python sionna_beamforming_sim.py

echo ""
echo "Simulation complete!"
