# -*- mode: python ; coding: utf-8 -*-
"""One-folder Linux build for the Debian package; one-file mode is intentionally absent."""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parents[1]

a = Analysis(
    [str(Path(SPECPATH) / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="usb-cctv-recorder",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="usb-cctv-recorder",
)
