<script lang="ts">
  import { isWritten } from '$lib/exam-session';
  import { optionLetter } from '$lib/questions';
  import type { QuestionPublic } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';
  import { composeStaged, splitStaged, STAGE_LABELS, STAGES } from '$lib/viva';

  let {
    question,
    number,
    selected,
    text = '',
    disabled = false,
    onchoose,
    ontext
  }: {
    question: QuestionPublic;
    number: number;
    selected: number | undefined;
    text?: string;
    disabled?: boolean;
    onchoose: (option: number | null) => void;
    ontext: (text: string) => void;
  } = $props();
  let image = $derived(mediaUrl(question.figure_image_path));
  let written = $derived(isWritten(question.type));
  let staged = $derived(question.type === 'image_case' && (question.stages?.length ?? 0) > 0);
  // Raw per-stage text is kept locally so typing is never re-trimmed under the cursor;
  // the autosaved answer is the composed, headed text the grader reads.
  let parts = $state<Record<string, string>>({});
  let seeded = '';
  $effect(() => {
    if (staged && seeded !== question.id) {
      seeded = question.id;
      parts = { ...splitStaged(text) };
    }
  });

  function setStage(stage: string, value: string) {
    parts[stage] = value;
    ontext(composeStaged(parts));
  }
  const PROMPT: Record<string, string> = {
    seq: 'Write your answer as you would in the paper. It is marked against a fixed, cited scheme after you submit.',
    image_case: 'Describe the findings, then give the diagnosis, differentials, and next step.',
    viva: 'Answer as you would to the examiner.'
  };
</script>

<article class="panel p-5 sm:p-6" aria-labelledby="q-{question.id}">
  <p class="label">Question {number}{question.topic ? ` · ${question.topic}` : ''}</p>
  <p id="q-{question.id}" class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{question.stem}</p>
  {#if image}
    <div class="mt-4 overflow-hidden rounded-xl bg-stage">
      <img src={image} alt="Radiology image for question {number}" class="mx-auto max-h-[55dvh] w-auto" />
    </div>
  {/if}
  {#if staged}
    <fieldset class="mt-4 flex flex-col gap-3" {disabled}>
      <legend class="label">Answer each stage of the station; each is marked against its own cited points.</legend>
      {#each STAGES as stage, i (stage)}
        <label class="block">
          <span class="text-sm font-medium text-ink">{i + 1}. {STAGE_LABELS[stage]}</span>
          <textarea
            class="field mt-1 min-h-20 w-full leading-relaxed"
            maxlength="1500"
            value={parts[stage] ?? ''}
            oninput={(event) => setStage(stage, event.currentTarget.value)}
          ></textarea>
        </label>
      {/each}
      <span class="block text-right font-mono text-xs text-muted">{text.length}/8000</span>
    </fieldset>
  {:else if written}
    <label class="mt-4 block">
      <span class="label">{PROMPT[question.type] ?? 'Your answer'}</span>
      <textarea
        class="field mt-1.5 min-h-48 w-full leading-relaxed"
        maxlength="8000"
        value={text}
        {disabled}
        oninput={(event) => ontext(event.currentTarget.value)}
      ></textarea>
      <span class="mt-1 block text-right font-mono text-xs text-muted">{text.length}/8000</span>
    </label>
  {:else}
    <fieldset class="mt-4" {disabled}>
      <legend class="sr-only">Options</legend>
      <div class="flex flex-col gap-2">
        {#each question.options as option, i (i)}
          <label
            class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-[0.9375rem] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]
              {selected === i ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}"
          >
            <input type="radio" name="option-{question.id}" value={i} checked={selected === i} onchange={() => onchoose(i)} class="sr-only" />
            <span class="font-mono text-xs font-semibold text-muted">{optionLetter(i)}</span>
            <span class="text-ink">{option}</span>
          </label>
        {/each}
      </div>
    </fieldset>
    {#if selected !== undefined && !disabled}
      <button type="button" class="link mt-3 text-sm" onclick={() => onchoose(null)}>Clear answer</button>
    {/if}
  {/if}
</article>
