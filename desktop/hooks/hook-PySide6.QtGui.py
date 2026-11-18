"""Keep the standard Qt hook, excluding unused plugins and their dependencies."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# Virtual Keyboard is GPLv3/commercial. This Widgets application does not use it.
# PDF and extra raster formats are also unnecessary for SVG controls and PNG export.
image_plugins = {"qsvg.dll", "qico.dll", "qjpeg.dll", "qgif.dll"}
binaries = [entry for entry in binaries
            if Path(entry[0]).name.lower() != "qtvirtualkeyboardplugin.dll"
            and (Path(entry[0]).parent.name.lower() != "imageformats"
                 or Path(entry[0]).name.lower() in image_plugins)]
