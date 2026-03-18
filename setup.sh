#!/bin/bash
# Setup script: installs dependencies and builds SlideToPDF.app
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="/opt/homebrew/bin/python3.13"

# Check prerequisites
if ! command -v brew &>/dev/null; then
    echo "Error: Homebrew is required. Install from https://brew.sh"
    exit 1
fi

if [ ! -f "$PYTHON" ]; then
    echo "=== Installing Python 3.13 via Homebrew ==="
    brew install python@3.13 python-tk@3.13
fi

echo "=== Installing Python dependencies ==="
$PYTHON -m pip install --break-system-packages opencv-python pillow pillow-heif pyinstaller

echo ""
echo "=== Building SlideToPDF.app ==="
rm -rf build dist SlideToPDF.spec
$PYTHON -m PyInstaller --windowed --name SlideToPDF --onedir --noconfirm slide_to_pdf.py

echo ""
echo "=== Done! ==="
echo "App is at: $SCRIPT_DIR/dist/SlideToPDF.app"
echo "You can drag it to your Applications folder."
