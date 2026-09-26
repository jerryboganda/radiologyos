<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationList from '$lib/components/CitationList.svelte';
  import WrittenFeedback from '$lib/components/questions/WrittenFeedback.svelte';
  import type { AttemptOut } from '$lib/types/assessment';
  import type { SessionStep, VivaStepView } from '$lib/types/session';
  import { mediaUrl } from '$lib/viewer';

  let { sessionId, step }: { sessionId: string; step: SessionStep } = $props();
  let viva = $derived(step.viva as VivaStepView);
  let text = $state('');
  let sending = $state(false);
  let image = $derived(mediaUrl(viva.question?.figure_image_path));
  let graded = $derived<AttemptOut | null>(
    viva.status === 'graded' && viva.result && viva.question
      ? {
          attempt_id: null,
          question_id: viva.question.id,
          type: viva.question.type,
          score: viva.result.score ?? 0,
          max_score: viva.result.max_score ?? 0,
          explanation: '',
          points: viva.result.points ?? [],
          feedback: viva.result.feedback ?? '',
          model_answer: viva.result.model_answer ?? '',
          key_findings: viva.result.key_findings ?? [],
          citations: viva.citations
        }
      : null
  );
</script>

<div class="flex flex-col gap-4">
  <div class="rounded-xl border border-line bg-surface-2/50 p-4">
    <p class="label">{viva.mode === 'graded' ? 'Examiner question' : 'Self-review prompt'}{viva.topic ? ` · ${viva.topic.title}` : ''}</p>
    <p class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{viva.question?.stem ?? viva.prompt}</p>
    {#if image}
      <div class="mt-3 overflow-hidden rounded-xl bg-stage"><img src={image} alt="Radiology figure for the viva question" class="mx-auto max-h-[50dvh] w-auto" /></div>
    {/if}
    {#if viva.mode === 'self_review' && viva.citations.length}
      <p class="mt-3 text-xs text-muted">Based on: <CitationList citations={viva.citations} class="mt-1 inline-flex" /></p>
    {/if}
  </div>

  {#if !viva.answer_text}
    <form
      method="POST"
      action="?/stepAnswer"
      use:enhance={() => {
        sending = true;
        return async ({ update }) => {
          await update({ reset: false });
          sending = false;
        };
      }}
    >
      <input type="hidden" name="session_id" value={sessionId} />
      <input type="hidden" name="step_no" value={step.step_no} />
      <label class="block">
        <span class="label">Your answer, as you would say it aloud</span>
        <textarea name="answer_text" bind:value={text} maxlength="8000" class="field mt-1.5 min-h-40 w-full leading-relaxed" disabled={sending}></textarea>
        <span class="mt-1 block text-right font-mono text-xs text-muted">{text.length}/8000</span>
      </label>
      <button type="submit" class="btn btn-primary mt-2" disabled={!text.trim() || sending}>{sending ? 'Sending…' : 'Submit answer'}</button>
    </form>
  {:else}
    <div class="rounded-xl border border-line p-4">
      <p class="label">Your answer</p>
      <p class="mt-1 text-sm leading-relaxed whitespace-pre-line text-ink-2">{viva.answer_text}</p>
    </div>
    {#if graded}
      <WrittenFeedback result={graded} />
    {:else if viva.status === 'pending'}
      <p class="text-sm text-ink-2" role="status">Being marked against its cited scheme. The result appears here when it is ready.</p>
      <CitationList citations={viva.citations} />
    {:else if viva.status === 'failed'}
      <p class="text-sm text-warn" role="status">Marking failed. Compare your answer with the cited sources below.</p>
      <CitationList citations={viva.citations} />
    {:else if viva.reference}
      <div class="rounded-xl border border-line bg-surface-2/50 p-4">
        <p class="label">Compare with the source</p>
        {#if viva.reference.heading}<p class="mt-1 font-medium text-ink">{viva.reference.heading}</p>{/if}
        <p class="mt-1 text-sm leading-relaxed whitespace-pre-line text-ink-2">{viva.reference.text}</p>
        <CitationList citations={viva.citations} class="mt-3" />
      </div>
    {/if}
  {/if}
</div>
