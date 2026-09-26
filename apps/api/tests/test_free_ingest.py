"""Free-first bulk ingest (ADR 0027): text-first PDF routing, the Mistral
transport, and gateway fallback to Claude. No network: HTTP is mocked and the
PDFs are synthetic, built in memory."""

from __future__ import annotations

import ctypes
import io
import json
from typing import Any

import httpx
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import pytest
from packages.library import text_first
from packages.library.text_first import pages_with_pictures, text_only_pages
from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError
from packages.models.gateway import build_calls, load_agent, run_agent
from packages.models.mistral import MistralTransport
from packages.models.transports import MultiTransport
from PIL import Image

LINES = [f"Chest radiograph review line {i}: consolidation, effusion, pneumothorax."
         for i in range(14)]


def _pdf(lines: list[str], picture: bool = False) -> bytes:
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(595, 842)
    font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    for n, line in enumerate(lines):
        obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, 11.0)
        buf = ctypes.create_string_buffer((line + "\x00").encode("utf-16-le"))
        pdfium_c.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(pdfium_c.FPDF_WCHAR)))
        pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 50, 800 - 14 * n)
        pdfium_c.FPDFPage_InsertObject(page.raw, obj)
    if picture:  # an X-ray-sized raster on the page, like a textbook figure
        image = pdfium.PdfImage.new(doc)
        image.set_bitmap(pdfium.PdfBitmap.from_pil(Image.new("RGB", (300, 300), (90, 90, 90))))
        image.set_matrix(pdfium.PdfMatrix().scale(250, 250).translate(170, 150))
        page.insert_obj(image)
    page.gen_content()
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _image_pdf() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (800, 1000), (200, 200, 200)).save(out, format="PDF")
    return out.getvalue()


def test_text_page_skips_vision_but_pictures_scans_and_short_text_do_not() -> None:
    assert text_only_pages(_pdf(LINES), {1: 900}) == {1}
    assert text_only_pages(_pdf(LINES, picture=True), {1: 900}) == set()
    assert pages_with_pictures(_pdf(LINES, picture=True), [1]) == {1}
    assert text_only_pages(_image_pdf(), {1: 900}) == set()
    assert text_only_pages(_pdf(LINES), {1: 120}) == set()  # below MIN_CHARS


def test_multi_column_pages_go_to_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_inspector

    real = pdf_inspector.process_pdf_bytes

    class Columns:
        def __init__(self, report: Any) -> None:
            self._r = report

        def __getattr__(self, name: str) -> Any:
            return [1] if name == "pages_with_columns" else getattr(self._r, name)

    monkeypatch.setattr(pdf_inspector, "process_pdf_bytes", lambda b: Columns(real(b)))
    assert text_only_pages(_pdf(LINES), {1: 900}) == set()


def test_any_inspector_failure_sends_pages_to_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_inspector

    def broken(_: bytes) -> Any:
        raise RuntimeError("unreadable")

    monkeypatch.setattr(pdf_inspector, "process_pdf_bytes", broken)
    assert text_only_pages(_pdf(LINES), {1: 900}) == set()
    assert text_first.text_only_pages(b"not a pdf", {1: 900}) == set()


def _call(**kw: Any) -> ModelCall:
    base: dict[str, Any] = {"model": "mistral-large-2512", "effort": "low", "system_prompt": "s",
                            "user_prompt": "u", "output_schema": {"type": "object"},
                            "files": (("page-00001.png", b"\x89PNG"),), "backend": "mistral"}
    return ModelCall(**{**base, **kw})


def _ok(content: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}],
                                     "usage": {"prompt_tokens": 1500, "completion_tokens": 300}})


def _transport(responses: list[httpx.Response], seen: list[dict[str, Any]]) -> MistralTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return responses.pop(0)

    return MistralTransport(client=httpx.Client(transport=httpx.MockTransport(handler)),
                            min_interval_s=0, _sleep=lambda _: None)


def test_mistral_sends_image_and_schema_and_reports_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 32)
    seen: list[dict[str, Any]] = []
    result = _transport([_ok({"a": 1})], seen).run(_call())
    assert result.output == {"a": 1} and result.backend == "mistral" and result.cost_usd == 0
    assert result.usage == {"input_tokens": 1500, "output_tokens": 300}
    body = seen[0]
    assert body["response_format"]["json_schema"]["strict"] is True
    image = body["messages"][1]["content"][1]
    assert image["type"] == "image_url" and image["image_url"].startswith("data:image/png;base64,")


def test_mistral_retries_rate_limits_then_raises_usage_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 32)
    seen: list[dict[str, Any]] = []
    assert _transport([httpx.Response(429), _ok({"a": 1})], seen).run(_call()).output == {"a": 1}
    with pytest.raises(UsageLimitError):
        _transport([httpx.Response(429)] * 6, []).run(_call())


def test_mistral_falls_back_to_json_mode_when_strict_schema_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 32)
    seen: list[dict[str, Any]] = []
    assert _transport([httpx.Response(400), _ok({"a": 2})], seen).run(_call()).output == {"a": 2}
    assert seen[1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen[1]["messages"][0]["content"]


def test_mistral_refuses_without_key_or_with_non_image_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ModelCallError):
        MistralTransport().run(_call())
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 32)
    with pytest.raises(ModelCallError):
        _transport([], []).run(_call(files=(("notes.pdf", b"%PDF"),)))


class _Backend:
    def __init__(self, outcome: Any) -> None:
        self.outcome, self.calls = outcome, 0

    def run(self, call: ModelCall) -> ModelResult:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return ModelResult(output=self.outcome, duration_ms=1, cost_usd=0.0,
                           backend=call.backend)


VALID_PAGE = {"page_type": "text", "blocks": [], "figures": [], "topics": []}


@pytest.mark.parametrize("failure", [UsageLimitError("quota"), ModelCallError("boom"),
                                     {"not": "a page"}])
def test_gateway_falls_back_from_mistral_to_claude(failure: Any) -> None:
    mistral, claude = _Backend(failure), _Backend(VALID_PAGE)
    transport = MultiTransport({"mistral": mistral, "claude_code": claude})
    _, result = run_agent(transport, "page_parse", "prompt")
    assert (mistral.calls, claude.calls, result.backend) == (1, 1, "claude_code")


def test_gateway_uses_only_backends_the_transport_serves() -> None:
    claude = _Backend(VALID_PAGE)
    _, result = run_agent(MultiTransport({"claude_code": claude}), "page_parse", "prompt")
    assert result.backend == "claude_code" and claude.calls == 1
    with pytest.raises(UsageLimitError):  # every target exhausted: the job pauses
        run_agent(MultiTransport({"mistral": _Backend(UsageLimitError("q")),
                                  "claude_code": _Backend(UsageLimitError("q"))}),
                  "page_parse", "prompt")


def test_bulk_agents_are_mistral_first_and_image_case_stays_on_claude() -> None:
    for name in ("page_parse", "paper_topics", "knowledge_extract", "topic_classify"):
        backends = [c.backend for c in build_calls(load_agent(name), "p")]
        assert backends == ["mistral", "claude_code"], name
    assert [c.backend for c in build_calls(load_agent("image_case"), "p")] == ["claude_code"]
