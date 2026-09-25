from __future__ import annotations

from uuid import UUID

from apps.api.app.preview.library import search_chunks, search_figures
from apps.api.app.preview.state import PreviewState


def ask(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    query: str,
) -> dict[str, object]:
    results = search_chunks(state, tenant_id, query, limit=4)
    figures = search_figures(state, tenant_id, query, limit=2)
    messages = state.thread(tenant_id, owner_id)
    citations: list[dict[str, object]] = []
    if not results:
        answer = "I do not have a grounded answer in the selected sources."
    else:
        sentences = []
        for chunk, _score in results:
            sentence = chunk.text.strip().splitlines()[0]
            sentences.append(f"{sentence} [1]")
            citations.append(
                {
                    "source_id": str(chunk.source_id),
                    "page_no": chunk.page_no,
                    "block_id": str(chunk.block_start),
                    "bbox": [0.0, 0.0, 0.0, 0.0],
                }
            )
        answer = " ".join(sentences)
    messages.append({"role": "user", "content": query})
    messages.append({"role": "assistant", "content": answer, "citations": citations})
    state.set_thread(tenant_id, owner_id, messages[-40:])
    return {
        "mode": "preview",
        "answer": answer,
        "citations": citations,
        "figures": tuple(
            {
                "id": str(figure.id),
                "page_no": figure.page_no,
                "caption": figure.caption,
                "modality": figure.modality,
                "image_key": figure.image_key,
            }
            for figure in figures
        ),
        "grounding": "mock_lexical_preview",
    }
