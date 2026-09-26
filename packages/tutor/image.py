"""Images attached to tutor questions (ADR 0025): validation, cleaning, and reading.

An attached image is untrusted: only PNG, JPEG, and WebP are accepted (checked
by content, not by name), DICOM is refused outright (CLAUDE.md), nothing over
20 MB or 40 megapixels is decoded, and every accepted image is re-encoded, so
EXIF/XMP/text metadata (camera, location, software, embedded comments) is never
stored. The ``image_case`` vision agent then reads it into findings, an
impression, and differentials. That reading is AI output about the user's own
image: it steers retrieval and is shown labelled as an AI reading, but it is
never a citation; the answer is still cited to the owner's sources (or the
labelled web fallback). Nothing here logs image bytes or model text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from PIL import Image, ImageOps

from packages.library.parse_models import ImageCase
from packages.models.gateway import Transport, run_agent

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
IMAGE_AGENT = "image_case"
READ_PROMPT = "Image attached by the candidate to a tutor question."
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
           "WEBP": ("webp", "image/webp")}
RETRIEVAL_CHARS = 1200


class ImageRejected(Exception):
    """An upload that is not an acceptable image; ``status`` is the HTTP status to return."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CleanImage:
    data: bytes
    extension: str
    content_type: str
    width: int
    height: int
    sha256: str


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def _check_raw(data: bytes) -> str:
    if not data:
        raise ImageRejected(415, "The file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected(413, "Images must be 20 MB or smaller.")
    if data[128:132] == b"DICM":
        raise ImageRejected(415, "DICOM files are not accepted; attach a PNG, JPEG, or WebP "
                                 "screenshot with no patient identifiers.")
    kind = sniff(data[:16])
    if kind is None:
        raise ImageRejected(415, "Attach a PNG, JPEG, or WebP image.")
    return kind


def _encode(image: Image.Image, kind: str) -> bytes:
    out = BytesIO()
    if kind == "JPEG":
        rgb = image if image.mode in ("RGB", "L") else image.convert("RGB")
        rgb.save(out, format="JPEG", quality=92)
    elif kind == "WEBP":
        image.save(out, format="WEBP", quality=92)
    else:
        image.save(out, format="PNG")
    return out.getvalue()


def clean_image(data: bytes) -> CleanImage:
    """Validate and re-encode an upload (metadata dropped); raises ImageRejected."""
    kind = _check_raw(data)
    try:
        with Image.open(BytesIO(data)) as opened:
            if opened.format != kind:
                raise ImageRejected(415, "The file content does not match an allowed image type.")
            if opened.width * opened.height > MAX_PIXELS:
                raise ImageRejected(413, "The image has too many pixels (40 megapixels at most).")
            opened.load()
            upright = ImageOps.exif_transpose(opened) or opened
            encoded = _encode(upright, kind)
            width, height = upright.size
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise ImageRejected(415, "The image could not be read.") from exc
    if len(encoded) > MAX_IMAGE_BYTES:
        raise ImageRejected(413, "Images must be 20 MB or smaller.")
    extension, content_type = FORMATS[kind]
    return CleanImage(encoded, extension, content_type, width, height,
                      hashlib.sha256(encoded).hexdigest())


def read_image(transport: Transport, data: bytes, extension: str) -> ImageCase:
    """The vision agent's structured reading of an attached image."""
    # v1 reads a lone image; v2 needs the library page text around a figure.
    parsed, _ = run_agent(transport, IMAGE_AGENT, READ_PROMPT,
                          files=[(f"attached.{extension}", data)], version=1)
    return cast(ImageCase, parsed)


def retrieval_text(question: str, reading: ImageCase | None) -> str:
    """Question plus the reading's key terms, for keyword and dense retrieval."""
    if reading is None:
        return question
    terms = [reading.impression, *reading.differentials, *reading.topics,
             reading.modality, reading.anatomy, *reading.findings]
    extra = " ".join(" ".join(t.split()) for t in terms if t.strip())
    return f"{question} {extra}"[:RETRIEVAL_CHARS]
