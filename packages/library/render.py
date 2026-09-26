"""Render sources into page images plus native text blocks with provenance.

PDFs are rendered with pypdfium2 (Apache/BSD licensed). DOCX and PPTX are
converted to PDF by headless LibreOffice first, so every source becomes a list
of pages with a PNG at study resolution and positioned text blocks. Standalone
images become a one-page source. Bounding boxes are normalised to 0..1 with a
top-left origin so they are independent of render resolution.
"""

from __future__ import annotations

import io
import shutil
import subprocess  # nosec B404 - fixed argv, no shell
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from packages.library.formats import SourceKind

RENDER_DPI = 150
MAX_IMAGE_EDGE = 4096


@dataclass(slots=True)
class NativeBlock:
    block_no: int
    text: str
    bbox: tuple[float, float, float, float]
    kind: str = "paragraph"


@dataclass(slots=True)
class RenderedPage:
    page_no: int
    width: float
    height: float
    png: bytes
    blocks: list[NativeBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks)


class RenderError(RuntimeError):
    """A source could not be rendered."""


def office_to_pdf(data: bytes, extension: str, soffice: str = "soffice") -> bytes:
    """Convert DOCX/PPTX to PDF; retry once with a normalised archive.

    Some real decks are valid ZIPs that LibreOffice still refuses to load
    (observed with a 117 MB compiled PPTX); rewriting the archive with
    standard deflate and [Content_Types].xml first makes them loadable.
    """
    try:
        return _soffice_convert(data, extension, soffice)
    except RenderError:
        return _soffice_convert(repack_office_zip(data), extension, soffice)


def repack_office_zip(data: bytes) -> bytes:
    import zipfile

    try:
        source = zipfile.ZipFile(io.BytesIO(data))
        names = source.namelist()
    except zipfile.BadZipFile as exc:
        raise RenderError("document is not a readable archive") from exc
    buffer = io.BytesIO()
    first = [n for n in names if n == "[Content_Types].xml"]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in first + [n for n in names if n not in first]:
            target.writestr(name, source.read(name))
    return buffer.getvalue()


def _soffice_convert(data: bytes, extension: str, soffice: str) -> bytes:
    binary = shutil.which(soffice)
    if binary is None:
        raise RenderError("LibreOffice (soffice) is not installed")
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / f"input.{extension}"
        source.write_bytes(data)
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [binary, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", work,
             str(source)],
            capture_output=True,
            timeout=1800,
            check=False,
        )
        output = Path(work) / "input.pdf"
        if result.returncode != 0 or not output.is_file():
            raise RenderError("LibreOffice could not convert the document")
        return output.read_bytes()


def iter_pages(kind: SourceKind, data: bytes, extension: str) -> Iterator[RenderedPage]:
    if kind is SourceKind.IMAGE:
        yield _image_page(data)
        return
    pdf_bytes = data if kind is SourceKind.PDF else office_to_pdf(data, extension)
    yield from _pdf_pages(pdf_bytes)


def count_pages(kind: SourceKind, data: bytes) -> int | None:
    if kind is SourceKind.IMAGE:
        return 1
    if kind is SourceKind.PDF:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(data))
    return None


def _image_page(data: bytes) -> RenderedPage:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        converted = image.convert("RGB")
    converted.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buffer = io.BytesIO()
    converted.save(buffer, format="PNG")
    return RenderedPage(1, float(converted.width), float(converted.height), buffer.getvalue())


def _pdf_pages(pdf_bytes: bytes) -> Iterator[RenderedPage]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            bitmap = page.render(scale=RENDER_DPI / 72)
            buffer = io.BytesIO()
            # optimize=True costs ~4x the CPU for ~0.5% smaller files.
            bitmap.to_pil().save(buffer, format="PNG")
            blocks = native_blocks(page.get_textpage(), width, height)
            yield RenderedPage(index + 1, float(width), float(height), buffer.getvalue(), blocks)
    finally:
        document.close()


def native_blocks(textpage: object, width: float, height: float) -> list[NativeBlock]:
    """Group pdfium text rectangles into paragraph-like blocks."""
    rects = _text_rects(textpage)
    blocks: list[NativeBlock] = []
    current: list[tuple[float, float, float, float, str]] = []
    for rect in rects:
        if current and rect[1] - current[-1][3] > 0.6 * max(rect[3] - rect[1], 1.0):
            blocks.append(_merge(len(blocks), current, width, height))
            current = []
        current.append(rect)
    if current:
        blocks.append(_merge(len(blocks), current, width, height))
    return [block for block in blocks if block.text.strip()]


def _text_rects(textpage: object) -> list[tuple[float, float, float, float, str]]:
    tp = textpage
    count = tp.count_rects()  # type: ignore[attr-defined]
    rects: list[tuple[float, float, float, float, str]] = []
    for index in range(count):
        left, bottom, right, top = tp.get_rect(index)  # type: ignore[attr-defined]
        text = tp.get_text_bounded(left, bottom, right, top)  # type: ignore[attr-defined]
        if text.strip():
            # Convert to a top-down y axis: y0 is distance of the top edge from the top.
            rects.append((left, -top, right, -bottom, text.strip()))
    rects.sort(key=lambda r: (round(r[1], 0), r[0]))
    return rects


def _merge(
    block_no: int,
    rects: list[tuple[float, float, float, float, str]],
    width: float,
    height: float,
) -> NativeBlock:
    x0 = min(r[0] for r in rects)
    x1 = max(r[2] for r in rects)
    y0 = min(r[1] for r in rects)
    y1 = max(r[3] for r in rects)
    text = " ".join(r[4] for r in rects)
    bbox = (
        _clamp(x0 / width),
        _clamp((y0 + height) / height),
        _clamp(x1 / width),
        _clamp((y1 + height) / height),
    )
    return NativeBlock(block_no, text, bbox)


def _clamp(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def crop_png(png: bytes, bbox: tuple[float, float, float, float]) -> bytes:
    """Crop a normalised region from a page image at its original resolution."""
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        w, h = image.size
        box = (int(bbox[0] * w), int(bbox[1] * h), int(bbox[2] * w), int(bbox[3] * h))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            raise RenderError("figure region is too small to crop")
        cropped = image.crop(box)
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
