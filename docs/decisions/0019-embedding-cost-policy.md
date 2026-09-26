# 0019 — Embedding cost policy: pay once, query free, hard stop at 195M tokens

- Status: accepted
- Date: 2026-09-26
- Amends: ADR 0010 (embeddings), ADR 0009 ("no local models") for embeddings only

The owner wants the Voyage bill kept at zero and no surprise charges.

**Models.** Documents and figure descriptions are embedded once through the Voyage API
with `voyage-4-large`, inside the 200M free tokens per model per account. The whole
library is about 3.3M tokens, roughly $0.40 at list price and $0 in practice. Every
query (search, tutor, question topics) and every question-stem dedupe is embedded free on
our own server by the open-weight, Apache-2.0 `voyage-4-nano`. It runs in the
`embedder` container on the project's default network only (alias `radbrain-embedder`),
and shares the Voyage 4 embedding space, so its query vectors match the API's document
vectors directly.

**Pay once.** A tenant-scoped `embedding_cache` (RLS, key begins with `tenant_id`) stores
one vector per normalised text. Unchanged text never costs tokens twice, including after
re-chunking, reprocessing, a crash or a retry. Document embedding waits until the vision
pass has produced the final text. Paid batches are committed as soon as they return, and
`--reprocess` only re-queues jobs that still have work. The Batch API is not used,
because free tokens do not apply to it.

**Hard stop.** Every paid request first checks the lifetime ledger
(`app.embedding_tokens_total()`) against **195M tokens**. If the request would pass the
cap, nothing is sent, the step is marked `skipped` / `embedding_budget_exhausted`, and a
**red** alert goes to the admins: a push notification, a banner and a log line. An
**amber** alert fires at 150M. There is no silent fallback, and raising the cap needs a
`models.yaml` change and an amendment to this ADR.

**New dependencies.** torch (CPU), sentence-transformers and transformers, in the
embedder image only.

**Pins.**
- `voyageai/voyage-4-nano` is pinned to HF revision `67fabc9bef010dabc5f6024aa1b1b6b93410426f` and
  baked into the image, which runs offline.
- `transformers` must stay at or below 5.8.1: the model's remote code uses `create_causal_mask`
  arguments that were removed in 5.9.
- Locally the embedder is behind the `embedder` compose profile, so CI's runtime job does not
  download torch and the model. Production always runs it.
