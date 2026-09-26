# M7 portability — five-minute demo

- Status: a script for a live demo; **not release evidence** (ADR 0008). M7 is the
  durable Markdown/Obsidian-compatible vault with round-trip link reading (ADR 0031,
  ADR 0034). Certified local mode, mobile and institution SSO are out of scope
  (ADR 0009).
- Data: synthetic material or the owner's own tenant only. Never patient images. The
  export ZIP holds the owner's study content: keep it on the owner's machine, never
  commit it, and never share it (personal uploads are never redistributed).
- Needs:
  - a signed-in browser;
  - at least one source with extracted concepts and claims, and a few cards. These
    come from the knowledge and card agents, so producing them is **[model]** (the
    Claude token, ADR 0010). The export itself calls no model;
  - Obsidian installed on the demo machine (optional; any Markdown viewer works);
  - a repository checkout with Python 3.12 for the read-back step.
- Related: [data handling](../runbooks/data-handling.md) §6 (export), ADR 0018,
  ADR 0031, ADR 0034; gate `evals/checks/test_m7_portability.py`.

## 0:00 — Export the vault

1. **Settings → Export my data**. Wait for *Ready to download*, then **Download ZIP**.
2. Unzip it. Open `manifest.json` and point at `vault_files`: the number of files
   under `vault/`.

## 0:45 — The vault as plain Markdown

1. Open `vault/index.md`. It links every concept, source and card deck, and says that
   every claim and card cites its source and page.
2. Open one file under `vault/concepts/`. Point out:
   - YAML front matter with `radbrain_id`, `type`, `title`, `aliases` and
     `curriculum_code`;
   - each claim as a bullet with a block id (`^claim-…`), its verbatim evidence
     quote, and `Source: [[sources/<slug>|Title]], p. N (blocks p3-b4)`: source, page
     and the blocks whose bounding boxes hold the evidence;
   - **Related** concepts as `[[wikilinks]]` with their relation.
3. Open a file under `vault/cards/`. Each card cites its source and page the same way.
4. File names end in the first eight hex digits of the row id, so two concepts with
   the same name never collide.

## 1:45 — Open it in Obsidian

1. In Obsidian choose **Open folder as vault** and pick the `vault/` folder.
2. Click a concept's source link. It opens the source note, whose **backlinks**
   list every concept that cites it.
3. Open **Graph view**. Concepts, sources and decks form one connected graph.
4. Point out that user text cannot forge structure: a title containing `[[`, `#tag`,
   `^block` or HTML shows as escaped text, not as a link, tag or markup.

## 2:45 — Round trip: read the vault back

From the repository root, run this against the downloaded ZIP (the path is your own
download; nothing is uploaded anywhere):

```python
import zipfile
from apps.worker.app.datarights.vault_links import read_vault

with zipfile.ZipFile("radbrain-export.zip") as zf:
    files = {n: zf.read(n).decode() for n in zf.namelist() if n.startswith("vault/")}
index = read_vault(files)
print(len(index.ids), "ids;", len(index.links), "links;",
      len(index.broken), "broken;", len(index.citations), "citations")
```

Expected: every concept, source and deck file maps back to its `radbrain_id`,
`broken` is 0, and each citation resolves to a source id, a page range and, for
claims, the `(page, block)` pairs. Open one cited source in the web reader at that
page and block to show that the provenance still resolves.

## 3:45 — What M7 does and does not do

- Does: a durable, byte-stable vault inside every account export, built from the
  caller's rows under RLS, and a reader that maps files, links and citations back to
  row ids.
- Does not: import an edited vault back into radbrain. The round trip is read-only
  (ADR 0034).
- Proofs to name: `evals/checks/test_m7_portability.py` (wikilinks resolve, ids read
  back, escaping) and the runtime-role export proof
  `evals/checks/test_data_rights_live.py`, which builds the vault from live rows and
  reads it back in CI.

## 4:30 — Clean up

Delete the unzipped folder and the ZIP from the demo machine if it is not the owner's
own. The server copy of the ZIP expires after 7 days.
