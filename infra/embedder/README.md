# radbrain embedder

A local CPU embedding service for `voyageai/voyage-4-nano` (Apache-2.0, about
0.34B parameters, same embedding space as the Voyage 4 API models). Query
embeddings cost nothing per call (ADR 0019). The API reaches it at
`EMBEDDER_URL=http://radbrain-embedder:8080`. It sits on the project network only
and publishes no port. If it is down, search falls back to lexical.

## Contract

- `GET /health` returns `200 {"status":"ok","model":"voyage-4-nano","dimensions":1024}`
  once the model is loaded. It returns `503` with `status` set to `loading` or
  `error` before that.
- `POST /embed` takes `{"texts": [...], "input_type": "query" | "document"}` and
  returns `{"model":"voyage-4-nano","dimensions":1024,"embeddings":[[...]]}` in
  input order. The vectors are L2-normalised float32, truncated to 1024
  dimensions (Matryoshka).
  - It accepts 1–64 texts of at least 1 character each. Texts longer than 16,000
    characters are cut to 16,000.
  - Invalid input returns `422`. The error body never echoes the input text.
  - Until the model has loaded, it returns `503`.
- Queries and documents get the model's own retrieval prompts through
  `encode_query` / `encode_document`.

Logs record `input_type`, counts, and timings only. They never contain text.

## Build

The image downloads the model at build time from a pinned Hugging Face commit
(`ARG MODEL_REVISION`) and then runs offline (`HF_HUB_OFFLINE=1`). The build fails
unless a smoke step loads the model and gets unit-length `(1, 1024)` vectors.
Only CI builds the image (`build-images.yml` → `ghcr.io/<owner>/radiologyos-embedder:<sha>`).

`transformers` is pinned to 5.8.1. The model's remote code calls
`create_causal_mask(input_embeds=..., cache_position=...)`, and 5.9.0 removed
both arguments. Re-check that call before you bump `transformers` or
`MODEL_REVISION`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `EMBEDDER_THREADS` | `2` | `torch.set_num_threads`; match the container's `cpus` |
| `EMBEDDER_BATCH_SIZE` | `4` | encode batch size; bounds peak memory |
| `EMBEDDER_MODEL_DIR` | `/opt/model` | model directory baked into the image |

The service runs one uvicorn worker and serialises inference. The model's
sequence length is capped at 8,192 tokens so peak memory stays under the 3 GiB
limit; 16,000 characters of ordinary text is well below that.

## Tests

`python -m pytest -q infra/embedder` runs the contract tests with a fake model.
They need no torch and no model download.
