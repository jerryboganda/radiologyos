# radbrain local embedder: voyageai/voyage-4-nano (Apache-2.0) on CPU (ADR 0019).
# The model is baked in from a pinned Hugging Face commit, the runtime is
# offline, and the build fails unless the model loads and yields 1024-d vectors.
FROM python:3.12-slim

ARG MODEL_ID=voyageai/voyage-4-nano
# Commit of voyageai/voyage-4-nano `main`, resolved 2026-09-26. Re-check the
# transformers cap in requirements.txt before bumping it.
ARG MODEL_REVISION=67fabc9bef010dabc5f6024aa1b1b6b93410426f

LABEL org.opencontainers.image.title="radbrain-embedder" \
      radbrain.model.id="${MODEL_ID}" \
      radbrain.model.revision="${MODEL_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOKENIZERS_PARALLELISM=false \
    EMBEDDER_MODEL_DIR=/opt/model

RUN useradd --system --user-group --create-home --uid 10001 --shell /usr/sbin/nologin embedder

WORKDIR /srv
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Root-owned and read-only to the runtime user. The throwaway HF_HOME keeps
# download caches out of the image and out of the runtime user's cache.
RUN HF_HOME=/tmp/hf-build python -c "from huggingface_hub import snapshot_download; \
snapshot_download(repo_id='${MODEL_ID}', revision='${MODEL_REVISION}', \
local_dir='/opt/model', ignore_patterns=['docs/*'])" \
    && rm -rf /tmp/hf-build /opt/model/.cache \
    && chmod -R a+rX /opt/model

# No network from here on. HF_HOME stays writable: transformers copies the
# model's remote code into its modules cache when loading.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/home/embedder/.cache/huggingface

COPY app.py ./
USER embedder

# Build-time smoke test through the same loader the service uses.
RUN python -c "import app, numpy as np; \
m = app.load_model(); \
q = m.encode_query(['test'], truncate_dim=1024, normalize_embeddings=True); \
d = m.encode_document(['test'], truncate_dim=1024, normalize_embeddings=True); \
assert q.shape == (1, 1024) and d.shape == (1, 1024), (q.shape, d.shape); \
assert q.dtype == np.float32, q.dtype; \
assert abs(float(np.linalg.norm(q[0])) - 1.0) < 1e-3, 'query vector not unit length'; \
assert not np.allclose(q, d), 'query and document prompts were not applied'; \
print('embedder smoke ok', q.shape, q.dtype)"

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
