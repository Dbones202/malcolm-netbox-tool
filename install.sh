#!/usr/bin/env bash
# Offline Installer for NetBox Excel Device Importer (Malcolm / Air-Gapped Linux Systems)
# Self-healing installer: Supports python3-venv, bundled virtualenv, and isolated lib/ target mode.
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "Installing NetBox Excel Importer (Air-Gapped Offline Mode)"
echo "============================================================"

# 1. Verify Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "[-] Error: 'python3' executable could not be found."
    echo "    Please install Python 3 (3.8 or higher) before running this installer."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]); then
    echo "[-] Error: Python version $PY_VERSION is not supported."
    echo "    NetBox Excel Importer requires Python 3.8+."
    exit 1
fi

echo "[+] Detected Python $PY_VERSION ($(which python3))"

# 2. Check for offline wheels directory
WHEELS_DIR="$SCRIPT_DIR/wheels"
if [ ! -d "$WHEELS_DIR" ] || [ -z "$(ls -A "$WHEELS_DIR" 2>/dev/null)" ]; then
    echo "[-] Error: 'wheels' directory not found or empty in $SCRIPT_DIR."
    echo "    Ensure you extracted the complete offline bundle archive."
    exit 1
fi

# 3. Setup isolated environment
VENV_DIR="$SCRIPT_DIR/venv"
LIB_DIR="$SCRIPT_DIR/lib"
INSTALL_MODE=""

echo "[+] Setting up isolated environment..."

# Strategy A: Try system python3 -m venv
if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/pip" ]; then
    echo "    (Found existing virtual environment at $VENV_DIR)"
    INSTALL_MODE="venv"
else
    echo "    Attempting to create virtual environment with 'python3 -m venv'..."
    if python3 -m venv "$VENV_DIR" 2>/dev/null && [ -x "$VENV_DIR/bin/pip" ]; then
        echo "[+] Virtual environment created successfully with standard venv."
        INSTALL_MODE="venv"
    else
        echo "    [!] Standard 'python3 -m venv' is unavailable (missing python3-venv / ensurepip)."
        echo "    Attempting fallback with bundled standalone 'virtualenv'..."
        
        # Strategy B: Use bundled virtualenv package directly from wheels
        if python3 -c "
import sys, glob
for whl in glob.glob('$WHEELS_DIR/*.whl'):
    sys.path.insert(0, whl)
import virtualenv
virtualenv.cli_run(['$VENV_DIR', '--no-download', '--no-periodic-update'])
" 2>/dev/null && [ -x "$VENV_DIR/bin/python" ]; then
            echo "[+] Virtual environment created successfully via bundled virtualenv."
            INSTALL_MODE="venv"
        else
            # Strategy C: Fallback to isolated local lib/ directory
            echo "    [!] Virtualenv creation bypassed. Using isolated library target: $LIB_DIR"
            mkdir -p "$LIB_DIR"
            INSTALL_MODE="lib"
        fi
    fi
fi

# 4. Install packages in offline mode
if [ "$INSTALL_MODE" = "venv" ]; then
    VENV_PIP="$VENV_DIR/bin/pip"
    echo "[+] Installing packages into virtual environment from offline wheels..."
    
    # If pip executable is inside venv
    if [ -x "$VENV_PIP" ]; then
        "$VENV_PIP" install --no-index --find-links "$WHEELS_DIR" --upgrade pip setuptools wheel > /dev/null 2>&1 || true
        "$VENV_PIP" install --no-index --find-links "$WHEELS_DIR" netbox-excel-importer > /dev/null 2>&1 || \
        "$VENV_PIP" install --no-index --find-links "$WHEELS_DIR" "$SCRIPT_DIR"
    else
        # Run pip module via venv python
        "$VENV_DIR/bin/python" -c "
import sys, glob
for whl in glob.glob('$WHEELS_DIR/*.whl'):
    sys.path.insert(0, whl)
import pip._internal.cli.main as pip_cli
pip_cli.main(['install', '--no-index', '--find-links', '$WHEELS_DIR', 'netbox-excel-importer'])
"
    fi
else
    # Install into lib/ directory
    echo "[+] Installing packages into local library folder from offline wheels..."
    python3 -c "
import sys, glob
for whl in glob.glob('$WHEELS_DIR/*.whl'):
    sys.path.insert(0, whl)
import pip._internal.cli.main as pip_cli
pip_cli.main(['install', '--no-index', '--find-links', '$WHEELS_DIR', '--target', '$LIB_DIR', 'netbox-excel-importer'])
"
fi

# 5. Create direct launcher executable script
cat << 'EOF' > "$SCRIPT_DIR/netbox-excel-importer"
#!/usr/bin/env bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ -x "$SCRIPT_DIR/venv/bin/netbox-excel-importer" ]; then
    exec "$SCRIPT_DIR/venv/bin/netbox-excel-importer" "$@"
elif [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    exec "$SCRIPT_DIR/venv/bin/python" -m netbox_importer.cli "$@"
elif [ -d "$SCRIPT_DIR/lib" ]; then
    export PYTHONPATH="$SCRIPT_DIR/lib:$SCRIPT_DIR/src:$PYTHONPATH"
    exec python3 -m netbox_importer.cli "$@"
else
    echo "[-] Error: Netbox Importer is not installed. Please run ./install.sh first."
    exit 1
fi
EOF
chmod +x "$SCRIPT_DIR/netbox-excel-importer"

# Also symlink run.sh for convenience
ln -sf "$SCRIPT_DIR/netbox-excel-importer" "$SCRIPT_DIR/run.sh"

echo ""
echo "============================================================"
echo "✓ Installation Complete!"
echo "============================================================"
echo "You can now run the tool directly using:"
echo "  ./netbox-excel-importer --help"
echo "  or"
echo "  ./run.sh --help"
echo ""
echo "Examples:"
echo "  ./netbox-excel-importer generate-template test_devices.xlsx"
echo "  ./netbox-excel-importer validate test_devices.xlsx"
echo "  ./netbox-excel-importer import test_devices.xlsx --dry-run"
echo "  ./netbox-excel-importer import test_devices.xlsx"
echo "============================================================"
