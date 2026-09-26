"""Unit tests for the library pipeline building blocks (no database, no network)."""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from apps.api.tests.pdf_fixture import make_pdf
from packages.library import storage
from packages.library.chunking import BlockInput, build_chunks, looks_like_heading
from packages.library.formats import SourceKind, UnsupportedUpload, clean_title, detect_format
from packages.library.render import RenderError, count_pages, crop_png, iter_pages
from PIL import Image

TENANT = UUID("20000000-0000-0000-0000-000000000002")
OTHER = UUID("20000000-0000-0000-0000-0000000000ff")
SOURCE = UUID("30000000-0000-0000-0000-000000000003")


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 120, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_detects_pdf_and_images_by_content() -> None:
    assert detect_format(make_pdf([["x"]]), "notes.bin").kind is SourceKind.PDF
    assert detect_format(_jpeg(), "scan.png").kind is SourceKind.IMAGE


def test_rejects_dicom_regardless_of_extension() -> None:
    dicom = b"\x00" * 128 + b"DICM" + b"\x00" * 64
    with pytest.raises(UnsupportedUpload, match="DICOM"):
        detect_format(dicom, "study.pdf")


def test_rejects_non_office_zip_and_unknown_bytes() -> None:
    with pytest.raises(UnsupportedUpload):
        detect_format(b"PK\x03\x04" + b"\x00" * 64, "archive.zip")
    with pytest.raises(UnsupportedUpload):
        detect_format(b"hello world", "notes.txt")


def test_office_zip_is_accepted_by_part_name() -> None:
    docx = b"PK\x03\x04" + b"\x00" * 26 + b"word/document.xml" + b"\x00" * 64
    assert detect_format(docx, "Notes.DOCX").kind is SourceKind.DOCX


def test_clean_title_strips_extension_and_whitespace() -> None:
    assert clean_title("C:\\x\\CHEST  (Compiled )_1.pptx") == "CHEST (Compiled ) 1"
    assert clean_title("a_b.pdf") == "a b"
    assert clean_title(".pdf") == "Untitled source"


def test_object_keys_are_tenant_prefixed_and_validated() -> None:
    key = storage.original_key(TENANT, SOURCE, "PDF")
    assert key == f"tenants/{TENANT}/sources/{SOURCE}/original.pdf"
    storage.require_tenant_key(TENANT, key)
    with pytest.raises(PermissionError):
        storage.require_tenant_key(OTHER, key)
    with pytest.raises(PermissionError):
        storage.require_tenant_key(TENANT, f"tenants/{TENANT}/../{OTHER}/x")
    with pytest.raises(ValueError):
        storage.original_key(TENANT, SOURCE, "p/df")


def test_memory_store_round_trip_and_prefix_delete() -> None:
    store = storage.MemoryObjectStore()
    store.put("tenants/a/sources/s/1", b"one", "text/plain")
    store.put_file("tenants/a/sources/s/2", io.BytesIO(b"two"), "text/plain")
    store.put("tenants/a/sources/t/1", b"keep", "text/plain")
    assert store.get("tenants/a/sources/s/2") == b"two"
    assert store.delete_prefix("tenants/a/sources/s/") == 2
    assert list(store.objects) == ["tenants/a/sources/t/1"]


def test_s3_store_refuses_deletes_outside_a_tenant() -> None:
    store = storage.S3ObjectStore("http://x", "b", "k", "s")
    with pytest.raises(PermissionError):
        store.delete_prefix("")


def test_pdf_renders_pages_with_positioned_native_text() -> None:
    data = make_pdf([["Pulmonary alveolar proteinosis", "Crazy paving"], ["Page two text"]])
    pages = list(iter_pages(SourceKind.PDF, data, "pdf"))
    assert [p.page_no for p in pages] == [1, 2]
    assert pages[0].png.startswith(b"\x89PNG")
    assert "Pulmonary alveolar proteinosis" in pages[0].text
    for block in pages[0].blocks:
        x0, y0, x1, y1 = block.bbox
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    assert pages[0].blocks[0].bbox[1] < 0.2  # first line sits near the top
    assert count_pages(SourceKind.PDF, data) == 2


def test_image_source_is_one_page_and_crop_keeps_resolution() -> None:
    page = next(iter_pages(SourceKind.IMAGE, _jpeg(), "jpg"))
    assert (page.page_no, page.width, page.height) == (1, 64.0, 48.0)
    crop = crop_png(page.png, (0.0, 0.0, 0.5, 0.5))
    with Image.open(io.BytesIO(crop)) as image:
        assert image.size == (32, 24)
    with pytest.raises(RenderError):
        crop_png(page.png, (0.0, 0.0, 0.01, 0.01))


def test_heading_detection() -> None:
    assert looks_like_heading("Pulmonary alveolar proteinosis", 0)
    assert not looks_like_heading("Pulmonary alveolar proteinosis", 3)
    assert not looks_like_heading("This sentence ends with a period.", 0)


def test_chunks_keep_provenance_and_split_on_headings() -> None:
    blocks = [
        BlockInput(1, 0, "heading", "Chest"),
        BlockInput(1, 1, "paragraph", "word " * 50),
        BlockInput(2, 0, "heading", "Neuro"),
        BlockInput(2, 1, "paragraph", "brain " * 30),
    ]
    chunks = build_chunks(blocks)
    assert [c.heading for c in chunks] == ["Chest", "Neuro"]
    assert chunks[0].block_refs == [{"page": 1, "block": 0}, {"page": 1, "block": 1}]
    assert (chunks[1].page_from, chunks[1].page_to) == (2, 2)


def test_long_text_splits_under_the_word_ceiling() -> None:
    blocks = [BlockInput(p, 0, "paragraph", "term " * 200) for p in range(1, 7)]
    chunks = build_chunks(blocks)
    assert len(chunks) >= 3
    assert all(len(c.text.split()) <= 460 for c in chunks)
    assert all(c.page_to - c.page_from < 3 for c in chunks)


def test_empty_blocks_make_no_chunks() -> None:
    assert build_chunks([BlockInput(1, 0, "paragraph", "   ")]) == []
