#!/bin/bash
# Setup script for LLVM installation on macOS

echo "=========================================="
echo "Sionna RT - LLVM Setup Helper"
echo "=========================================="
echo ""

# Detect architecture
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    LLVM_PATH="/opt/homebrew/opt/llvm/lib/libLLVM.dylib"
    SHELL_RC="$HOME/.zshrc"
    echo "Detected: Apple Silicon (M1/M2/M3)"
else
    LLVM_PATH="/usr/local/opt/llvm/lib/libLLVM.dylib"
    SHELL_RC="$HOME/.zshrc"
    echo "Detected: Intel Mac"
fi

echo ""
echo "Checking for LLVM installation..."

if [ -f "$LLVM_PATH" ]; then
    echo "✓ LLVM is already installed at: $LLVM_PATH"
else
    echo "✗ LLVM not found at: $LLVM_PATH"
    echo ""
    echo "To install LLVM, run:"
    echo "  brew install --build-from-source llvm"
    echo ""
    echo "Note: This will compile LLVM from source and may take 30-60 minutes"
    echo ""
    read -p "Would you like to install LLVM now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing LLVM..."
        brew install --build-from-source llvm

        if [ $? -eq 0 ]; then
            echo "✓ LLVM installed successfully!"
        else
            echo "✗ LLVM installation failed. Please check the error messages above."
            exit 1
        fi
    else
        echo "Skipping LLVM installation."
        exit 0
    fi
fi

echo ""
echo "Configuring environment variable..."

# Check if DRJIT_LIBLLVM_PATH is already in shell config
if grep -q "DRJIT_LIBLLVM_PATH" "$SHELL_RC"; then
    echo "✓ DRJIT_LIBLLVM_PATH is already configured in $SHELL_RC"
else
    echo "Adding DRJIT_LIBLLVM_PATH to $SHELL_RC"
    echo "" >> "$SHELL_RC"
    echo "# Sionna RT - LLVM path for Dr.Jit" >> "$SHELL_RC"
    echo "export DRJIT_LIBLLVM_PATH=\"$LLVM_PATH\"" >> "$SHELL_RC"
    echo "✓ Environment variable added to $SHELL_RC"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "To apply the changes, either:"
echo "  1. Restart your terminal, OR"
echo "  2. Run: source $SHELL_RC"
echo ""
echo "Then you can run the simulation with:"
echo "  ./run.sh"
echo ""
