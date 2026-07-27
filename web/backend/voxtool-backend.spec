# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the VoxTool desktop backend.

Produces a self-contained `voxtool-backend` executable with Python, numpy and
nibabel inside, plus the compiled React UI as bundled data, so the desktop app
has no external runtime dependencies.
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

BACKEND_DIR = SPECPATH
FRONTEND_BUILD = os.environ.get(
    "VOXTOOL_FRONTEND_BUILD",
    os.path.abspath(os.path.join(BACKEND_DIR, "..", "frontend", "build")),
)

if not os.path.isfile(os.path.join(FRONTEND_BUILD, "index.html")):
    raise SystemExit(
        f"Frontend build not found at {FRONTEND_BUILD}.\n"
        "Run `npm run build` in web/frontend first."
    )

datas = [(FRONTEND_BUILD, "frontend")]
binaries = []
hiddenimports = [
    "waitress",
    "flask_cors",
    "local_mode",
    "ct_cache",
    "legacy_interpolator",
    "scan_store",
    "routes.scans",
    "routes.annotations",
]

# nibabel resolves several format handlers lazily, so static analysis misses them.
for pkg in ("nibabel",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("numpy")

a = Analysis(
    ["desktop_server.py"],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nothing in the desktop build may reach AWS, and these only bloat it.
        "boto3",
        "botocore",
        "matplotlib",
        "tkinter",
        "PyQt5",
        "PySide2",
        "IPython",
        "pytest",
        "scipy",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voxtool-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("VOXTOOL_TARGET_ARCH") or None,
    codesign_identity=None,
    entitlements_file=None,
)

# One-dir rather than one-file: no unpacking cost on every launch, so the app
# window appears in about a second instead of ten.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="voxtool-backend",
)
