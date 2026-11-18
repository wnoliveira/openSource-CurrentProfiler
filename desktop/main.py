"""Keep startup errors visible even in PyInstaller's windowed executable."""
from multiprocessing import freeze_support
import os
from pathlib import Path
import sys
import tempfile
import traceback


def startup_text(source, **values):
    """Use the saved language when Qt can load; preserve an English fallback.

    Startup reporting must also work when Qt itself is the missing dependency,
    so importing translation support is deliberately optional here.
    """
    try:
        from PySide6 import QtCore
        from current_scope.i18n import Translator, system_language

        settings = QtCore.QSettings("OpenInstrumentation", "IoTCurrentScope")
        preference = settings.value("language", "system")
        language = system_language() if preference == "system" else preference
        return Translator(language).text(source, **values)
    except Exception:
        return source.format(**values) if values else source


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from current_scope.self_test import run

        return run(Path(sys.argv[2]))
    try:
        # Import after the self-test branch so a frozen build can report
        # startup failures instead of disappearing without diagnostics.
        from current_scope.app import main as start

        return start()
    except Exception:
        details = traceback.format_exc()
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        log = base / "IoTCurrentScope" / "startup.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(details + "\n")
            message = startup_text("IoTCurrentScope could not start.")
            message += "\n\n" + startup_text("Details: {path}", path=log)
        except OSError:
            message = startup_text("IoTCurrentScope could not start.") + "\n\n" + details
        if sys.stderr is not None:
            sys.stderr.write(details)
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "IoTCurrentScope", 0x10)
        return 1


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
