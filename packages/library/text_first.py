"""PDF pages whose own text layer is good enough to skip the vision model (ADR 0027).

A page skips vision only when all of these hold:

* pdf-inspector finds a real, decodable text layer: the page is not routed to
  OCR, has no table, and the document has no font-encoding problems;
* pdfium finds no raster picture covering ``MAX_PICTURE_SHARE`` of the page
  (radiology images, photos, scanned figures);
* the stored native text has at least ``MIN_CHARS`` characters.

Anything the checks cannot read goes to vision, so a failure here costs quota,
never quality. Page numbers are 1-indexed, as stored in ``source_pages``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MIN_CHARS = 200
MAX_PICTURE_SHARE = 0.02


def text_only_pages(pdf_bytes: bytes, native_chars: Mapping[int, int]) -> set[int]:
    candidates = {page for page, chars in native_chars.items() if chars >= MIN_CHARS}
    if not candidates:
        return set()
    try:
        import pdf_inspector

        report: Any = pdf_inspector.process_pdf_bytes(pdf_bytes)
    except Exception:  # noqa: BLE001 - any inspector failure means "use vision"
        return set()
    if getattr(report, "has_encoding_issues", True):
        return set()
    flagged = set(report.pages_needing_ocr or ()) | set(report.pages_with_tables or ())
    candidates -= flagged
    try:
        return candidates - pages_with_pictures(pdf_bytes, candidates)
    except Exception:  # noqa: BLE001 - unreadable by pdfium: use vision
        return set()


def pages_with_pictures(pdf_bytes: bytes, pages: Iterable[int]) -> set[int]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    document = pdfium.PdfDocument(pdf_bytes)
    found: set[int] = set()
    try:
        for page_no in sorted(pages):
            if not 1 <= page_no <= len(document):
                found.add(page_no)
                continue
            page = document[page_no - 1]
            width, height = page.get_size()
            area = max(width * height, 1.0)
            for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=8):
                left, bottom, right, top = obj.get_bounds()
                if (right - left) * (top - bottom) / area >= MAX_PICTURE_SHARE:
                    found.add(page_no)
                    break
    finally:
        document.close()
    return found
