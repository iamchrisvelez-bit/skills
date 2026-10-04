#!/usr/bin/env bash
# Build Brainiac.app and Brainiac.dmg. Run on a Mac:  ./build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$HERE"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Brainiac.app has to be built on a Mac." >&2
  exit 1
fi

echo "1/5  Python environment"
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r "$ROOT/requirements.txt" pyinstaller

echo "2/5  Icon"
rm -rf build/Brainiac.iconset && mkdir -p build/Brainiac.iconset
PYTHONPATH="$ROOT" python - <<'PY'
from pathlib import Path
from brainiac.icon import png
out = Path("build/Brainiac.iconset")
for size in (64, 128, 256, 512, 1024):
    (out / f"src-{size}.png").write_bytes(png(size, mac=True))
PY
cd build/Brainiac.iconset
sips -z 16 16 src-1024.png --out icon_16x16.png >/dev/null
sips -z 32 32 src-1024.png --out icon_16x16@2x.png >/dev/null
cp icon_16x16@2x.png icon_32x32.png
cp src-64.png icon_32x32@2x.png
cp src-128.png icon_128x128.png
cp src-256.png icon_128x128@2x.png
cp src-256.png icon_256x256.png
cp src-512.png icon_256x256@2x.png
cp src-512.png icon_512x512.png
cp src-1024.png icon_512x512@2x.png
rm src-*.png
cd "$HERE"
iconutil -c icns build/Brainiac.iconset -o build/Brainiac.icns

echo "3/5  Bundle"
pyinstaller --noconfirm --clean --log-level WARN Brainiac.spec

echo "4/5  Sign (ad-hoc, for this Mac)"
codesign --force --deep --sign - dist/Brainiac.app

echo "5/5  Disk image"
rm -rf build/dmg && mkdir -p build/dmg
cp -R dist/Brainiac.app build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -quiet -volname Brainiac -srcfolder build/dmg -ov -format UDZO dist/Brainiac.dmg

echo
echo "Done:"
echo "  $HERE/dist/Brainiac.app"
echo "  $HERE/dist/Brainiac.dmg   (open it and drag Brainiac to Applications)"
