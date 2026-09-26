"""radbrain local embedder: voyageai/voyage-4-nano on CPU (ADR 0019).

GET /health answers 200 once the model is loaded and 503 while it loads (or if
loading failed). POST /embed returns 1024-dimension, L2-normalised float32
vectors in input order. Input text is never logged or echoed in errors; logs
carry counts and timings only.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, Field

MODEL_NAME = "voyage-4-nano"
DIMENSIONS = 1024
MAX_TEXTS = 64
MAX_CHARS = 16_000
# Bounds activation memory under the container's 3 GiB limit. 16k characters of
# ordinary text is roughly 4-5k tokens, so real inputs are never cut by this.
MAX_TOKENS = 8192

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("radbrain.embedder")


def _truncate(text: str) -> str:
    return text[:MAX_CHARS]


Text = Annotated[str, Field(min_length=1), AfterValidator(_truncate)]


class EmbedRequest(BaseModel):
    texts: list[Text] = Field(min_length=1, max_length=MAX_TEXTS)
    input_type: Literal["query", "document"]


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    embeddings: list[list[float]]


def _env_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def load_model() -> Any:
    """Load the model baked into the image; imports are lazy so tests need no torch."""
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(_env_int("EMBEDDER_THREADS", 2))
    model = SentenceTransformer(
        os.environ.get("EMBEDDER_MODEL_DIR", "/opt/model"),
        device="cpu",
        trust_remote_code=True,
        local_files_only=True,
        # float32 on CPU: bf16 matmuls are slow without native support.
        model_kwargs={"attn_implementation": "sdpa", "dtype": torch.float32},
    )
    model.max_seq_length = min(model.max_seq_length or MAX_TOKENS, MAX_TOKENS)
    return model


def _load_in_background(app: FastAPI, loader: Callable[[], Any]) -> None:
    started = time.monotonic()
    try:
        app.state.model = loader()
    except Exception:
        app.state.failed = True
        logger.exception("model load failed")
        return
    logger.info("model loaded in %.1fs", time.monotonic() - started)


def _status_body(status: str) -> dict[str, Any]:
    return {"status": status, "model": MODEL_NAME, "dimensions": DIMENSIONS}


async def _health(request: Request) -> JSONResponse:
    state = request.app.state
    if state.model is None:
        return JSONResponse(_status_body("error" if state.failed else "loading"), 503)
    return JSONResponse(_status_body("ok"))


def _embed(body: EmbedRequest, request: Request) -> EmbedResponse:
    state = request.app.state
    model = state.model
    if model is None:
        raise HTTPException(status_code=503, detail="model not ready")
    encode = model.encode_query if body.input_type == "query" else model.encode_document
    started = time.monotonic()
    # One inference at a time: bounds memory and keeps torch's thread pool uncontended.
    with state.lock:
        vectors = encode(
            body.texts,
            truncate_dim=DIMENSIONS,
            normalize_embeddings=True,
            batch_size=state.batch_size,
            convert_to_numpy=True,
        )
    embeddings: list[list[float]] = vectors.tolist()
    if len(embeddings) != len(body.texts) or any(len(row) != DIMENSIONS for row in embeddings):
        logger.error("embedding shape mismatch count=%d", len(body.texts))
        raise HTTPException(status_code=500, detail="embedding shape mismatch")
    logger.info(
        "embedded input_type=%s count=%d ms=%d",
        body.input_type,
        len(body.texts),
        (time.monotonic() - started) * 1000,
    )
    return EmbedResponse(model=MODEL_NAME, dimensions=DIMENSIONS, embeddings=embeddings)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    """422 without pydantic's `input` echo, so caller logs never receive source text."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in errors]
    return JSONResponse({"detail": detail}, 422)


def create_app(loader: Callable[[], Any] = load_model) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Load off the event loop so /health can answer 503 while the model loads.
        thread = threading.Thread(
            target=_load_in_background, args=(app, loader), name="model-loader", daemon=True
        )
        app.state.loader_thread = thread
        thread.start()
        yield

    app = FastAPI(
        title="radbrain embedder",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.model = None
    app.state.failed = False
    app.state.lock = threading.Lock()
    app.state.batch_size = _env_int("EMBEDDER_BATCH_SIZE", 4)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_api_route("/health", _health, methods=["GET"])
    app.add_api_route("/embed", _embed, methods=["POST"], response_model=EmbedResponse)
    return app


app = create_app()
