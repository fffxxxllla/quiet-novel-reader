# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

root = Path(SPECPATH)
a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "assets" / "reader.ico"), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
# Qt uses the ICU API supplied by Windows. An unrelated Poppler installation
# on the build PATH has an incompatible ICU with version-suffixed exports.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.casefold() != "icuuc.dll"
              and not (Path(entry[0]).name.casefold().startswith("icudt")
                       and Path(entry[0]).suffix.casefold() == ".dll")]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="静读",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=bool(os.environ.get("QNR_CONSOLE_BUILD")), disable_windowed_traceback=False,
    icon=str(root / "assets" / "reader.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="静读")
