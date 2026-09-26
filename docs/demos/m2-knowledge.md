# M2 knowledge — five-minute demo

- Status: a script for a live demo; **not release evidence** (ADR 0008). Run it only
  on the owner's personal tenant, with synthetic material or the owner's own study
  material. Never use patient images.
- Needs:
  - the Claude token installed (ADR 0010);
  - at least two parsed sources that cover the same topics, with knowledge
    extraction finished;
  - a signed-in browser.
- Related: [knowledge runbook](../runbooks/knowledge.md),
  [library runbook](../runbooks/library.md), ADR 0016, ADR 0023, ADR 0030.

## 0:00 — Concepts from two books, no duplicates

1. Open **Knowledge** and search for a concept both books cover (for example,
   *renal oncocytoma*). One concept appears, and its claims cite both books.
2. Open the source's reader, then **Library → source → steps**. Point out
   `knowledge_extraction` and `knowledge_depth`, which shows counts such as
   `conflicts:1,pairs:1,notes:4`.

## 1:00 — The cited concept note

1. On the concept page, **Concept note** shows the definition, imaging by
   modality, pearls and pitfalls. Every sentence carries footnote numbers.
2. Open **Sources for this note**. Each number is a claim with its reader chip;
   click one to land on the exact page and block.
3. The header reads *Draft · every sentence cited*, with the number of sentences
   dropped because they were unsupported. Click **Mark verified**. It is refused
   while a conflict is open (see 3:00).

## 2:00 — Differential tree, concept map, figures, quiz

1. The **Differential tree** lists cited discriminators under each differential.
   Graph-only links are labelled *no cited discriminator yet*.
2. In the **Concept map**, press Tab to reach it, then use the arrow keys to move
   between concepts; Enter opens one. Switch the theme to show that light and dark
   both work.
3. **Related figures** are the figures on the pages the claims cite.
4. Pick an exam and click **Quiz me**. Five cited SBAs on the concept are generated
   on the Questions page.

## 3:00 — Source conflicts and "trust source"

1. Under **Source conflicts**, a card shows both claims side by side, the model's
   verdict (*true conflict*, *both valid in different contexts*, or *same fact*),
   its rationale, and the claims it relied on.
2. Click **Trust source B**. B stays active, A becomes superseded, and the decision
   is audited. Back in the note, **Mark verified** is now available.

## 4:00 — Duplicates and undo

1. Open **Knowledge → Review → Possible duplicate concepts**. A pair the resolver
   was unsure about waits here. Click **Merge them**. The smaller concept's page now
   redirects to the survivor, which gains its names and claims.
2. Under **Recent merges**, click **Undo merge**. The claims, links and names go
   back exactly.

## 4:30 — Tables and re-process

1. Open a page that has a table. The reader's **Tables** tab shows it as rows.
   Selecting it highlights the block on the page.
2. Search for a term that appears only in the table. The table shows up under
   **Tables**.
3. Click **Re-process** on the source. Failed pages are read again; finished work
   and unchanged text cost nothing.
