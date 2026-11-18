# Build on Windows with: python -m PyInstaller --clean --noconfirm IoTCurrentScope.spec
from importlib.metadata import distribution
import json
from pathlib import Path
import shutil
import sys
from PySide6 import QtCore

root = Path(SPECPATH)
licenses = root / "build" / "licenses"
licenses.mkdir(parents=True, exist_ok=True)
for path in (root / "licenses").rglob("*"):
    if path.is_file():
        target = licenses / path.relative_to(root / "licenses")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
for name in ("LICENSE", "THIRD_PARTY.md"):
    shutil.copyfile(root / name, licenses / name)
shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python.txt")
# Record the installed versions and preserve every license/notice supplied by
# the wheels. The release review still needs matching Qt library sources and
# the notices for the actual collected DLLs; this inventory is evidence, not a
# claim that every third-party obligation has been satisfied automatically.
dependency_versions = {}
for name in ("numpy", "pyqtgraph", "pyserial", "PySide6", "PySide6_Essentials",
             "PySide6_Addons", "shiboken6"):
    package = distribution(name)
    dependency_versions[name] = package.version
    for path in package.files or []:
        if any(word in path.name.lower() for word in ("license", "copying", "copyright", "notice")):
            target = licenses / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package.locate_file(path), target)
(licenses / "DEPENDENCIES.json").write_text(
    json.dumps(dependency_versions, indent=2), encoding="utf-8"
)

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    hookspath=[str(root / "hooks")],
    binaries=[],
    datas=[(str(root / "current_scope/assets"), "current_scope/assets"),
           (str(Path(QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath))
                / "qtbase_pt_BR.qm"), "translations"),
           (str(licenses), "licenses")],
    hiddenimports=["serial.tools.list_ports_windows", "PySide6.QtSvg"],
    excludes=["PyQt5", "PyQt6", "PySide2", "matplotlib", "scipy", "IPython"],
    noarchive=False,
)
if any("virtualkeyboard" in entry[0].lower() for entry in a.binaries):
    raise RuntimeError("Qt Virtual Keyboard (GPL/commercial) must not be bundled.")
pyz = PYZ(a.pure)
# Passing binaries/datas to EXE, without COLLECT, creates a onefile bundle.
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="IoTCurrentScope", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
