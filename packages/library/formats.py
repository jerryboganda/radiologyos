"""Upload format detection by content, not by file name.

DICOM is rejected in v1 (spec section 11): a ``DICM`` marker at byte 128 is a
hard refusal regardless of the extension the browser sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"


class UnsupportedUpload(ValueError):
    """The upload is not a supported study format."""


@dataclass(frozen=True, slots=True)
class DetectedFormat:
    kind: SourceKind
    extension: str
    mime_type: str


_OFFICE = {
    ".docx": DetectedFormat(
        SourceKind.DOCX,
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".pptx": DetectedFormat(
        SourceKind.PPTX,
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
}


def detect_format(data: bytes, filename: str) -> DetectedFormat:
    if len(data) > 132 and data[128:132] == b"DICM":
        raise UnsupportedUpload("DICOM files are not accepted")
    if data.startswith(b"%PDF-"):
        return DetectedFormat(SourceKind.PDF, "pdf", "application/pdf")
    if data.startswith(b"\xff\xd8\xff"):
        return DetectedFormat(SourceKind.IMAGE, "jpg", "image/jpeg")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedFormat(SourceKind.IMAGE, "png", "image/png")
    if data[:4] in (b"RIFF",) and data[8:12] == b"WEBP":
        return DetectedFormat(SourceKind.IMAGE, "webp", "image/webp")
    if data.startswith(b"PK\x03\x04"):
        lowered = filename.lower()
        for suffix, detected in _OFFICE.items():
            if lowered.endswith(suffix):
                marker = b"word/" if detected.kind is SourceKind.DOCX else b"ppt/"
                # The part names normally sit near the start of the archive; the
                # renderer rejects anything LibreOffice cannot open.
                if marker in data[:65536] or len(data) >= 65536:
                    return detected
        raise UnsupportedUpload("zip archive is not a .docx or .pptx document")
    raise UnsupportedUpload("unsupported file type; upload PDF, DOCX, PPTX, JPEG, or PNG")


def clean_title(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    title = " ".join(stem.replace("_", " ").split())
    return (title or "Untitled source")[:500]
