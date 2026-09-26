<script lang="ts">
  // "Similar figures" (nearest figure embeddings in your library) and "Quiz me"
  // (one SBA generated with this figure as F1, cited to your sources) for a
  // figure card (ADR 0025). The quiz posts to the question bank's action.
  let { figureId, examTarget = 'fcps2_theory' }: { figureId: string; examTarget?: string } = $props();
  const action = 'inline-flex min-h-8 items-center rounded-md border border-line px-2 py-1 font-mono text-[0.6875rem] text-ink-2 hover:border-accent hover:text-accent';
</script>

<div class="flex flex-wrap items-center gap-1.5">
  <a href="/library/figures/{encodeURIComponent(figureId)}/similar" class={action}>Similar figures</a>
  <form method="POST" action="/questions?/figure" class="contents">
    <input type="hidden" name="figure_id" value={figureId} />
    <input type="hidden" name="exam_target" value={examTarget} />
    <button type="submit" class={action} title="Generate one single-best-answer question on this figure">Quiz me</button>
  </form>
</div>
