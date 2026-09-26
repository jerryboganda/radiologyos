"""Pydantic output schemas for the ingestion agents (hard rule 2).

These models are the single source of truth: the JSON Schema passed to the
model is generated from them, and every model output is validated against them
before anything is stored.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BBox = list[float]


class ParsedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["heading", "paragraph", "list", "table", "caption", "other"]
    text: str = Field(description="Verbatim text as it appears on the page.")
    bbox: BBox = Field(
        min_length=4, max_length=4,
        description="[x0, y0, x1, y1] normalised 0..1, origin top-left.",
    )


class ParsedFigure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox: BBox = Field(min_length=4, max_length=4)
    is_radiology_image: bool
    caption: str = Field(description="Caption or label text visible near the figure; '' if none.")
    modality: str = Field(
        description="e.g. CT, MRI, X-ray, US, fluoroscopy, NM, diagram; '' if unclear."
    )
    anatomy: str
    description: str = Field(description="What is visibly shown, in radiology language.")
    findings: list[str]


class PageParse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_type: Literal["text", "slide", "question", "image_case", "table", "mixed", "blank"]
    blocks: list[ParsedBlock]
    figures: list[ParsedFigure]
    topics: list[str] = Field(description="Radiology topics covered, most specific first.")


class ImageCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modality: str
    anatomy: str
    visible_text: str = Field(description="Any text burned into or printed on the image.")
    findings: list[str]
    impression: str = Field(description="Most likely diagnosis, or '' if not determinable.")
    differentials: list[str]
    teaching_points: list[str]
    topics: list[str]
    confidence: Literal["low", "medium", "high"]


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema with every $ref inlined, for tools that reject $defs."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {key: resolve(value) for key, value in node.items() if key != "title"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved
