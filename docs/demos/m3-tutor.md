# M3 tutor — five-minute demo

- Status: script for a live demo; **not release evidence** (ADR 0008). Run it on the
  owner's personal tenant only, with synthetic or the owner's own study material —
  never patient images.
- Needs: the Claude token installed (ADR 0010), at least one parsed and embedded
  source with described figures, and a signed-in browser.
- Related: [tutor runbook](../runbooks/tutor.md), ADR 0013, ADR 0025.

## 0:00 — Ask and watch it stream (G8)

1. Open **Tutor**. Ask: *"What distinguishes a Bosniak IIF from a III cyst on CT?"*
2. Point out the stages (*Searching your library…*, *Writing a cited answer…*) and
   the grey italic block labelled **Draft · not yet checked** filling in as the
   model writes.
3. When *Checking every sentence…* finishes, the draft disappears and the final
   answer replaces it: every sentence carries a citation chip; any sentence the
   judge could not support is gone and counted in the footer
   (*"n unverifiable sentences removed"*).

## 1:00 — Follow up; memory (G17)

1. Ask two or three follow-ups in the same thread (*"And on MRI?"*, *"Management?"*).
2. In a long thread, the stage *Summarising earlier turns of this thread…* appears
   once the history passes its budget; follow-ups like *"what about in children?"*
   still resolve. The summary is never shown as a source and never cited.

## 2:00 — Ask about a spotter image (G7)

1. Click **Attach image** and choose a PNG/JPEG/WebP spotter screenshot (no patient
   identifiers). Try a `.dcm` file first to show the refusal message.
2. Ask *"What is this and what are the differentials?"* The stage *Reading your
   image…* appears once; the message shows the image with an **AI reading of your
   image · not a verified finding, not a citation** panel.
3. The answer teaches the suggested diagnosis and differentials **cited to your own
   excerpts and figures**; if your library does not cover it, labelled web sources
   follow (when allowed). A second question about the same image does not re-read it.

## 3:00 — Ask about this page (G15)

1. Open **Library → a source → any page**. Click **Ask about this page**.
2. The tutor opens with *Asking about <title> · p.N*. Ask *"Explain the key point of
   this page."* Citations point at that page first; the chip links back to it.

## 4:00 — Figures: similar and quiz (G7)

1. In the Reader's **Figures** tab (or search results), click **Similar figures** on
   a figure: the grid shows your nearest figures by meaning.
2. Click **Quiz me**: one SBA is generated with that figure as F1, checked, and
   opens first in **Questions → SBA**. Answer it and show the cited explanation.

## 5:00 — Wrap-up checks

- Settings → Data: an export ZIP contains `tutor-images/` and `data/tutor_images.json`.
- `TUTOR_STREAM_DRAFTS=false` turns the draft block off; answers are unchanged.
