# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import tomllib
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT_DIR = Path(SPECPATH).resolve()
PYPROJECT_PATH = ROOT_DIR / "pyproject.toml"

project_version = "0.0.0"
try:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project_version = str(pyproject.get("project", {}).get("version", project_version))
except Exception:
    pass

APP_BASE_NAME = "RainfallGraphCreator"
APP_NAME = f"{APP_BASE_NAME}_v{project_version}"
RASTERIO_HIDDENIMPORTS = collect_submodules("rasterio")
if "rasterio.sample" not in RASTERIO_HIDDENIMPORTS:
    RASTERIO_HIDDENIMPORTS.append("rasterio.sample")
RASTERIO_DATAS = collect_data_files("rasterio")

a = Analysis(
    ["run_uc_rainfall_gui.py"],
    pathex=[str(ROOT_DIR), str(ROOT_DIR / "src")],
    binaries=[],
    datas=RASTERIO_DATAS,
    hiddenimports=RASTERIO_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
