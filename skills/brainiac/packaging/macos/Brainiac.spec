# PyInstaller spec for Brainiac.app. Build with ./build.sh on a Mac.
import sys
from pathlib import Path

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parents[1]  # skills/brainiac
VERSION = "1.0.0"

# The standard library modules most often needed by code Brainiac writes and runs inside the app.
# (PyInstaller bundles only what Brainiac itself imports. Set BRAINIAC_PYTHON to use a full Python.)
STDLIB = """argparse array base64 bisect calendar collections contextlib copy csv dataclasses datetime decimal
difflib enum fnmatch fractions functools glob gzip hashlib heapq html http.client io itertools json logging math
numbers operator os pathlib pprint random re secrets shutil sqlite3 statistics string struct subprocess tarfile
tempfile textwrap time timeit typing unittest urllib.parse urllib.request uuid xml.etree.ElementTree zipfile
zoneinfo""".split()

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "brainiac" / "console.html"), "brainiac")],
    hiddenimports=["brainiac.demo_home", "brainiac.app", "brainiac.icon", "brainiac.evals", "anthropic"] + STDLIB,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Brainiac",
          console=sys.platform != "darwin", argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Brainiac")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Brainiac.app",
        icon=str(HERE / "build" / "Brainiac.icns"),
        bundle_identifier="com.brainiac.app",
        version=VERSION,
        info_plist={
            "CFBundleName": "Brainiac",
            "CFBundleDisplayName": "Brainiac",
            "CFBundleShortVersionString": VERSION,
            "LSMinimumSystemVersion": "11.0",
            # The app runs Brainiac in the background; its window is a Chrome/Edge/Brave app window
            # (with its own Dock icon), so the launcher itself stays out of the Dock.
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        },
    )
