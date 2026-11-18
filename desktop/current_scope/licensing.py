"""Make the bundled copyright and license notices readable without unpacking tools."""
from pathlib import Path
import sys


def license_directory():
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return root / "licenses"


def show_licenses(parent, translate=lambda text: text):
    from PySide6 import QtWidgets as W

    dialog = W.QDialog(parent)
    dialog.setPalette(parent.palette())
    dialog.setWindowTitle(translate("Licenses and third-party notices"))
    dialog.resize(800, 600)
    layout = W.QVBoxLayout(dialog)
    notice = W.QLabel(translate(
        "This application uses Qt/PySide6 under LGPLv3. Qt is copyright The Qt Company Ltd. and other contributors."
    ))
    notice.setWordWrap(True)
    layout.addWidget(notice)
    notices = W.QPlainTextEdit()
    notices.setReadOnly(True)
    folder = license_directory()
    texts = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            texts.append(f"{path.relative_to(folder)}\n\n{path.read_text(encoding='utf-8')}\n")
    # The source tree keeps project notices beside the application. Frozen
    # builds copy those same notices into the bundled licenses directory.
    if not getattr(sys, "frozen", False):
        for name in ("LICENSE", "THIRD_PARTY.md"):
            path = folder.parent / name
            if path.is_file():
                texts.insert(0, f"{name}\n\n{path.read_text(encoding='utf-8')}")
    notices.setPlainText("\n\n".join(texts))
    layout.addWidget(notices)
    buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
    buttons.button(W.QDialogButtonBox.StandardButton.Close).setText(translate("Close"))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
