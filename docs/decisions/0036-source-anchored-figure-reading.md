# 0036 — Figure diagnoses anchored to the owner's pages

- Status: accepted (owner chose "fix the design, then re-test Luna vs Sol", 2026-09-26)
- Amends: ADR 0035 (model rules unchanged; this changes what the figure agent reads)

## Why

A judged 19-slide test pass read the text of the slides well, but only about 30% of its figure
diagnoses matched the deck's own answers. It named a horseshoe kidney, an elbow fat-pad sign, a
rachitic rosary and a breast lipoma as something else.

`image_case` v1 diagnosed each cropped figure blind, although the deck states the answer on the
next slide. Its guesses were then stored as fact and could reach cards and questions.

## Decision

- **`image_case` v2** (`SourceImageCase`) receives the figure, its caption, and the text of its
  own page and **the page after it** (the answer slide).
  - A wider window (two pages either side) was tested and rejected. For a slide with no answer
    of its own, Luna took the next case's answer from two pages on.
  - v1 stays for tutor image uploads, which have no surrounding pages.
- The agent reports `impression_source` (`source` | `model`) and a verbatim `source_quote`.
- **Code checks the quote.** The words must occur, in order, in the supplied page text, and a
  question never counts. Only then is `figures.impression_origin = 'source'` and the quote kept.
  Otherwise the origin is `model`.
- **The description says where the impression came from.** A `model` impression is labelled
  "Impression (unverified model opinion)" in the stored description, so the owner sees that it
  is unverified.
  - `evidence_description()` strips that line wherever a figure becomes citable evidence:
    question and viva excerpts, image cards, and tutor figure excerpts.
- Migration `20260926_0105` adds `figures.impression_origin` and `figures.source_quote`. It is
  expand-only, and existing rows stay NULL, meaning not checked.
- **Knowledge extraction** gets two changes from the same review:
  - an evidence span that only quotes exam questions is rejected;
  - a claim cites the pages its evidence blocks are on, not the whole chunk's page range.

## Consequences

- Figures from decks with answer slides carry the deck's own diagnosis, with provenance.
- Figures without one keep useful findings but never teach an unverified diagnosis.
- The source's own errors pass through as quotes; conflict review remains the place to flag them.
