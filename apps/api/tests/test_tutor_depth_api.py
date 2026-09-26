"""Tutor depth over HTTP: images, Reader focus, memory, and draft streaming (ADR 0025).

Dependency overrides and fakes only (no database, no model, no object store);
the tenant/RLS proof for ``tutor_images`` lives in evals/checks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import tutor_images
from apps.api.app.core.config import get_settings
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.tutor_fakes import (
    HIT,
    PRINCIPAL,
    SOURCE_OK,
    StreamingFakeTransport,
    tutor_env,
)
from fastapi.testclient import TestClient
from packages.library.storage import tutor_image_prefix
from packages.models.claude_code import UsageLimitError
from packages.tutor import image as image_mod
from PIL import Image

client = TestClient(app)
SOURCE = uuid4()
PAGE_HIT = {**HIT, "id": uuid4(), "source_id": SOURCE, "page_from": 7, "page_to": 7,
            "text": "Dural tail sign favours meningioma."}


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    with tutor_env(monkeypatch) as state:
        yield state


def png() -> bytes:
    out = BytesIO()
    Image.new("RGB", (4, 3), (0, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def upload(data: bytes, name: str = "spotter.png") -> Any:
    return client.post("/v1/tutor/images", files={"file": (name, data, "image/png")})


def sse_events(body: dict[str, Any]) -> list[tuple[str, Any]]:
    response = client.post("/v1/tutor/ask/stream", json=body)
    assert response.status_code == 200, response.text
    parsed = []
    for frame in response.text.split("\n\n"):
        lines = [line for line in frame.split("\n") if line and not line.startswith(":")]
        if lines:
            parsed.append((lines[0].removeprefix("event: "),
                           json.loads(lines[1].removeprefix("data: "))))
    return parsed


def test_upload_stores_a_clean_image_privately_under_the_user_prefix(env: dict[str, Any]) -> None:
    response = upload(png())
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["content_type"], body["width"], body["height"]) == ("image/png", 4, 3)
    [key] = env["store"].objects
    assert key.startswith(tutor_image_prefix(PRINCIPAL.tenant_id, PRINCIPAL.user_id))
    assert key.endswith(f"{body['image_id']}.png") and env["session"].events == ["commit"]
    got = client.get(f"/v1/tutor/images/{body['image_id']}")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert got.headers["cache-control"] == "private, max-age=300"
    assert got.content == env["store"].objects[key][0]


@pytest.mark.parametrize(("data", "status"), [
    (b"GIF89a" + b"\0" * 40, 415),
    (b"\0" * 128 + b"DICM" + b"\0" * 32, 415),
    (b"", 415),
])
def test_upload_rejects_other_types_and_dicom(
    env: dict[str, Any], data: bytes, status: int
) -> None:
    assert upload(data, "scan.dcm").status_code == status
    assert env["store"].objects == {} and env["repo"].images == {}


def test_upload_rejects_images_over_the_size_limit(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tutor_images, "MAX_IMAGE_BYTES", 16)
    monkeypatch.setattr(image_mod, "MAX_IMAGE_BYTES", 16)
    assert upload(png()).status_code == 413 and env["store"].objects == {}


def test_uploads_and_reads_require_authentication() -> None:
    assert upload(png()).status_code == 401
    assert client.get(f"/v1/tutor/images/{uuid4()}").status_code == 401


@pytest.mark.parametrize("other", [
    Principal(user_id=uuid4(), tenant_id=PRINCIPAL.tenant_id),  # same tenant, other user
    Principal(user_id=uuid4(), tenant_id=uuid4()),  # other tenant
])
def test_another_user_cannot_read_or_ask_about_an_image(
    env: dict[str, Any], other: Principal
) -> None:
    image_id = upload(png()).json()["image_id"]
    env["principal"] = other
    assert client.get(f"/v1/tutor/images/{image_id}").status_code == 404
    response = client.post("/v1/tutor/ask", json={"question": "What is this?",
                                                  "image_id": image_id})
    assert response.status_code == 404 and env["transport"].calls == []


def test_image_question_is_read_once_and_steers_retrieval(env: dict[str, Any]) -> None:
    image_id = upload(png()).json()["image_id"]
    first = client.post("/v1/tutor/ask", json={"question": "What is this?",
                                               "image_id": image_id})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["image_reading"]["impression"] == "Alveolar proteinosis"
    assert body["image_id"] == image_id and body["grounding"] == "sources"
    assert env["transport"].agents() == ["vision", "tutor", "judge"]
    assert "alveolar or proteinosis" in env["search"][1]
    vision = env["transport"].calls[0]
    assert vision.files and vision.files[0][0] == "attached.png" and vision.tools == ("Read",)
    assert "<attached_image" in env["transport"].calls[1].user_prompt
    again = client.post("/v1/tutor/ask", json={"question": "Differentials?",
                                               "image_id": image_id,
                                               "thread_id": body["thread_id"]})
    assert again.status_code == 200
    assert env["transport"].agents().count("vision") == 1  # cached reading reused
    detail = client.get(f"/v1/tutor/threads/{body['thread_id']}").json()
    assert detail["messages"][0]["image_id"] == image_id
    assert detail["messages"][0]["image_reading"]["modality"] == "CT chest, axial"


def test_vision_failure_is_a_clear_status(env: dict[str, Any]) -> None:
    image_id = upload(png()).json()["image_id"]
    env["transport"].vision = UsageLimitError("limit")
    response = client.post("/v1/tutor/ask", json={"question": "What is this?",
                                                  "image_id": image_id})
    assert response.status_code == 429 and "commit" not in env["session"].events[1:]


def test_reader_focus_puts_the_page_first_and_names_it(env: dict[str, Any]) -> None:
    env["sources"][(PRINCIPAL.user_id, SOURCE)] = "Synthetic neuro deck"
    env["page_hits"] = [PAGE_HIT]
    body = client.post("/v1/tutor/ask", json={
        "question": "Explain this page", "focus": {"source_id": str(SOURCE), "page_no": 7},
    }).json()
    assert body["excerpts_considered"] == 2
    assert env["page_search"] == (PRINCIPAL.user_id, SOURCE, 7)
    prompt = env["transport"].calls[0].user_prompt
    assert '<reading note="' in prompt and "Synthetic neuro deck, page 7" in prompt
    assert prompt.index("Dural tail sign") < prompt.index("Crazy paving.")


def test_focus_on_someone_elses_source_is_404(env: dict[str, Any]) -> None:
    response = client.post("/v1/tutor/ask", json={
        "question": "Explain this page", "focus": {"source_id": str(SOURCE), "page_no": 7}})
    assert response.status_code == 404 and env["transport"].calls == []
    bad = client.post("/v1/tutor/ask", json={
        "question": "Explain", "focus": {"source_id": str(SOURCE), "page_no": 0}})
    assert bad.status_code == 422


def test_long_threads_fold_into_a_rolling_summary(env: dict[str, Any]) -> None:
    thread = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"}).json()
    thread_id = UUID(thread["thread_id"])
    for message in env["repo"].messages[thread_id]:
        message["content"] = "x" * 8000
    for _ in range(4):
        client.post("/v1/tutor/ask", json={"question": "More?", "thread_id": str(thread_id)})
    saved = env["repo"].memory[thread_id]
    assert saved.summary.startswith("Earlier the candidate") and saved.covered == 2
    assert saved.agent_version == "tutor_memory/v1"
    last_answer = [c for c in env["transport"].calls if "coverage" in str(c.output_schema)][-1]
    assert "<thread_summary" in last_answer.user_prompt


def test_memory_failure_never_blocks_the_answer(env: dict[str, Any]) -> None:
    thread_id = client.post("/v1/tutor/ask", json={"question": "Crazy paving?"}).json()[
        "thread_id"]
    for message in env["repo"].messages[UUID(thread_id)]:
        message["content"] = "x" * 6000
    env["transport"].memory = UsageLimitError("limit")
    for _ in range(4):
        response = client.post("/v1/tutor/ask", json={"question": "More?",
                                                      "thread_id": thread_id})
        assert response.status_code == 200
    assert UUID(thread_id) not in env["repo"].memory


def test_stream_sends_drafts_then_the_judged_answer(env: dict[str, Any]) -> None:
    env["transport"] = StreamingFakeTransport(SOURCE_OK)
    parsed = sse_events({"question": "What is crazy paving?"})
    names = [name for name, _ in parsed]
    assert names[0] == "status" and names[-2:] == ["answer", "done"]
    drafts = [data for name, data in parsed if name == "draft"]
    assert drafts and all(d["phase"] == "sources" for d in drafts)
    text = ""
    for op in drafts:
        text = op["text"] if "text" in op else text + op.get("append", "")
    assert text == "PAP shows crazy paving."
    judging = next(i for i, (n, d) in enumerate(parsed) if n == "status" and
                   d["stage"] == "judging")
    assert max(i for i, (n, _) in enumerate(parsed) if n == "draft") < judging
    assert dict(parsed)["answer"]["segments"][0]["support"] == "supported"


def test_stream_drafts_can_be_switched_off(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "tutor_stream_drafts", False)
    env["transport"] = StreamingFakeTransport(SOURCE_OK)
    assert "draft" not in [name for name, _ in sse_events({"question": "What is it?"})]


def test_stream_reports_reading_image(env: dict[str, Any]) -> None:
    image_id = upload(png()).json()["image_id"]
    parsed = sse_events({"question": "What is this?", "image_id": image_id})
    stages = [d["stage"] for n, d in parsed if n == "status"]
    assert stages[:3] == ["retrieving", "reading_image", "answering"]
    assert dict(parsed)["answer"]["image_reading"]["impression"] == "Alveolar proteinosis"
