#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/jefboneta/meshbook/main"
INSTALL_DIR="$HOME/meshbook"

echo "MeshBook installer"
echo "==================="
echo ""

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "ERROR: Python 3.10+ not found. Install it first:"
    echo "  https://www.python.org/downloads/"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
echo "Using: $PYTHON"
$PYTHON --version

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo ""
echo "Installing dependencies..."
curl -fsSL "$REPO/requirements.txt" -o requirements.txt
$PYTHON -m pip install --user --quiet -r requirements.txt

echo ""
echo "Downloading meshbook.py..."
curl -fsSL "$REPO/meshbook.py" -o meshbook.py
curl -fsSL "$REPO/README.md" -o README.md

echo ""
echo "==================="
echo "Installed to: $INSTALL_DIR"
echo ""
echo "Set MESHBOOK_MQTT_USER and MESHBOOK_MQTT_PASS before launching."
echo "To run:"
echo "  cd $INSTALL_DIR"
echo "  python meshbook.py"
