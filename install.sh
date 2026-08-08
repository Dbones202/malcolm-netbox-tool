#!/usr/bin/env bash
# Offline Installer for NetBox Excel Device Importer (Malcolm / Air-Gapped Systems)
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "Installing NetBox Excel Importer (Air-Gapped Offline Mode)"
echo "============================================================"

if [ ! -d "$SCRIPT_DIR/wheels" ]; then
    echo "Error: 'wheels' directory not found in $SCRIPT_DIR."
    echo "Ensure you extracted the complete offline bundle archive."
    exit 1
fi

python3 -m pip install --no-index --find-links ./wheels .

echo ""
echo "Installation complete!"
echo "Run 'netbox-excel-importer --help' to get started."
