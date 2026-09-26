# M1 library — five-minute demo

- Status: a script for a live demo; **not release evidence** (ADR 0008). Run it on the
  owner's personal tenant or a disposable synthetic tenant. Use a **synthetic**
  document only: for example a two-page PDF you made yourself, with a small table
  and a labelled diagram. Never use patient images.
- Needs:
  - a signed-in browser;
  - for the steps marked **[model]**: the Claude token in the api and worker
    (ADR 0010, ADR 0033);
  - for the steps marked **[Voyage]**: `VOYAGE_API_KEY` for embeddings and the
    reranker (ADR 0019, ADR 0028).
  - Without either, the source still becomes keyword-searchable; say so when a step
    is skipped.
- Related: [library runbook](../runbooks/library.md),
  [embeddings runbook](../runbooks/embeddings.md), ADR 0012, ADR 0028, ADR 0030.

## 0:00 — Upload

1. Open **Library → Upload sources**. Drop the synthetic PDF. The list shows it
   queued, then processing.
2. Drop a `.dcm` file. It is refused: DICOM is never accepted in v1.
3. Drop the same PDF again. No second source appears: the file hash matches, so the
   existing source is returned.

## 0:45 — Pipeline steps

1. Open the new source. While it runs, the step track shows **Render pages → Chunk
   text → Index → Searchable → Parse layout → Figures**. Hover a bar to see its state
   and detail.
2. Point out:
   - **Searchable** turns green before the vision pass finishes, so keyword search
     works early;
   - **Index** reads *skipped* when no Voyage key is set;
   - **Parse layout** and **Figures** run per page **[model]**. A usage-limit error
     defers the job for 30 minutes, and it resumes from the next unparsed page.
3. Reload the page. The finished steps stay finished; nothing restarts.

## 1:45 — Reader, provenance, figures, tables

1. On the reader, the header shows `text: native` or `text: vision` and the
   `vision:` status for the page.
2. Click into the page image and press **b** to show the block outlines. Click a
   block. The address becomes `?page=N&block=M`. Click **Copy link to #M**, open it
   in a new tab, and the same block is highlighted.
3. Zoom with **+** and **−**, press **1** for actual pixels and **0** to fit.
4. Open the **Figures** tab **[model]**. Each figure has its box on the page, a
   crop at original resolution, and its page provenance.
5. Open the **Tables** tab **[model]**. The table shows as rows and cells. Selecting
   it highlights its block on the page.

## 2:45 — Cited search, in reranked order

1. Open **Search** and search for a term from the synthetic document. The summary
   line reads *n passages · n figures · n tables*, and then *keyword + semantic* or
   *keyword only (embeddings off)*.
2. Point out the sections: **Figures**, **Tables** and **Passages**. Every passage
   is a cited block of the library. Nothing on this page is generated.
3. Click a passage. The reader opens at the cited page with the block highlighted.
4. **[Voyage]** On the host, `docker logs --since 5m radiologyos-api-1 2>&1 | grep
   reranked` shows one `reranked` line per search, with candidates, kept and tokens
   (counts only, no query text). The API response carries `reranked: true`. Without a
   key, or past the 195M cap, the log says `rerank_skipped` and the order stays the
   fused (RRF) order; the search still works.
5. Search for a term that appears only in the table. It is listed under **Tables**.

## 3:45 — Re-process

1. On the reader, click **Re-process**. The notice reads *Re-processing queued* (or
   how many failed pages will be read again), and the step track reappears.
2. While the job runs the button is disabled. A second request to the API is
   refused with 409, because the job is still running.
3. When the job finishes, point out that finished pages were not read again and
   unchanged text was not embedded twice. The step details show the counts.
4. Explain the boundary: only the source's uploader sees the button work; anyone
   else gets 404. The action writes a `source.reprocess_requested` audit row.

## 4:30 — Clean up and isolation

1. Delete the synthetic source from the Library. Its rows and every object under
   its storage prefix are removed, and a `source.deleted` audit row is written.
2. Close by naming the proofs: `evals/checks/test_m1_library.py`,
   `apps/api/tests/test_library_api.py`, and the runtime-role two-tenant proof
   `evals/checks/test_library_live.py` in CI. Another tenant never sees these rows.
