"""Render the English project README as a selectable, paginated PDF.

Run with the desktop virtual environment, which already supplies PySide6:
    desktop/.venv/Scripts/python.exe tools/export_readme_pdf.py
"""

import os
from pathlib import Path
import sys

# The Windows offscreen font backend can replace all glyphs with squares when
# printing. The native backend needs no visible window for a QTextDocument.
if sys.platform == "win32":
    os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]


def fit_document_images(document):
    """Keep the screenshot within the printable width without distorting it."""
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                image_format = fragment.charFormat().toImageFormat()
                source = QImage(str(ROOT / image_format.name()))
                if not source.isNull():
                    width = min(550, source.width())
                    image_format.setWidth(width)
                    image_format.setHeight(width * source.height() / source.width())
                    cursor = document.find(chr(0xFFFC), fragment.position())
                    cursor.setCharFormat(image_format)
            iterator += 1
        block = block.next()


def export_readme():
    """Use Qt's document layout for headings, tables, links and page breaks."""
    document = QTextDocument()
    document.setDefaultFont(QFont("Segoe UI", 10))
    document.setBaseUrl(QUrl.fromLocalFile(str(ROOT) + os.sep))
    document.setMarkdown((ROOT / "README.md").read_text(encoding="utf-8-sig"))
    fit_document_images(document)

    destination = ROOT / "README.pdf"
    writer = QPdfWriter(str(destination))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    # QTextDocument supplies its own 20 mm margins and page-number footer.
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setResolution(96)
    writer.setTitle("Open Source Current Profiler - project and measurement guide")
    writer.setCreator("Wenderson Oliveira - Open Source Current Profiler")
    document.print_(writer)
    del writer  # Finalize the PDF before opening it for inspection.
    return destination


def check_pdf(path):
    """Reject a PDF whose text was lost because of an unavailable font backend."""
    pdf = QPdfDocument()
    error = pdf.load(str(path))
    if error != QPdfDocument.Error.None_:
        raise RuntimeError(f"Could not open generated PDF: {error}")

    text = "\n".join(pdf.getAllText(page).text() for page in range(pdf.pageCount()))
    expected = (
        "Open Source Current Profiler",
        "Wenderson Oliveira",
        "In development",
        "GNU GPL",
        "Why 460800 baud",
    )
    missing = [phrase for phrase in expected if phrase not in text]
    if missing:
        raise RuntimeError(f"Generated PDF is missing text: {missing}")
    return pdf.pageCount()


def main():
    application = QApplication.instance() or QApplication([])
    path = export_readme()
    pages = check_pdf(path)
    print(f"Generated {path.name}: {pages} pages, {path.stat().st_size} bytes; text checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
