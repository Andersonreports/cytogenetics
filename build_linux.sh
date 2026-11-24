#!/usr/bin/env bash
# Build the Linux version: dist/CMCCytogeneticsReport-linux.tar.gz (program + README.txt).
# Run on Linux, or on Windows in WSL:  wsl.exe -d Ubuntu --exec bash build_linux.sh
#
# Uses a portable Python (uv's python-build-standalone) and leaves the C++ runtime out
# (build.spec), so the program needs only glibc 2.27: Ubuntu 18.04 or newer.
# Builds in a copy under ~/cyto-build with only the code, the blank template and the
# OMIM tables: samples/ and assets/WES report template/ (patient data) are never copied.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
B="$HOME/cyto-build"
UV="$HOME/cyto-uv/bin/uv"

[ -x "$UV" ] || { python3 -m venv "$HOME/cyto-uv"; "$HOME/cyto-uv/bin/pip" install -q uv; }
"$UV" python install 3.12

rm -rf "$B"; mkdir -p "$B/assets"
cp -r "$SRC/backend" "$SRC/frontend" "$SRC/database" "$SRC/build.spec" \
      "$SRC/requirements.txt" "$SRC/requirements-build.txt" "$B/"
cp "$SRC/assets/cmc_cytogenetics.docx" "$B/assets/"
find "$B" -name __pycache__ -prune -exec rm -rf {} +

cd "$B"
"$UV" venv -q -p 3.12 .venv
"$UV" pip install -q -p .venv/bin/python -r requirements.txt -r requirements-build.txt
.venv/bin/python -m PyInstaller build.spec --noconfirm --clean

P="$B/pkg/CMCCytogeneticsReport-linux"
rm -rf "$B/pkg"; mkdir -p "$P"
cp dist/CMCCytogeneticsReport "$P/"; chmod +x "$P/CMCCytogeneticsReport"
cat > "$P/README.txt" <<"EOF"
CMC Cytogenetics report tool - Linux
====================================

Works on Ubuntu 18.04 or newer (and other Linux PCs from 2018 on), 64-bit.

1. Install LibreOffice once (needed for the preview and PDF export):
       sudo apt install libreoffice-writer
2. Extract this folder anywhere, open a terminal in it and run:
       ./CMCCytogeneticsReport
   The tool opens in the web browser (http://127.0.0.1:5200).
   Keep the terminal open while using it; closing it stops the tool.

Options:  ./CMCCytogeneticsReport --port 5300      (if 5200 is in use)
          ./CMCCytogeneticsReport --lan            (let other PCs on the network use it)

Contains licensed OMIM data: for CMC staff only, do not share publicly.
EOF
mkdir -p "$SRC/dist"
tar -C "$B/pkg" -czf "$SRC/dist/CMCCytogeneticsReport-linux.tar.gz" CMCCytogeneticsReport-linux
echo "Built: dist/CMCCytogeneticsReport-linux.tar.gz"
