<script lang="ts">
  import Kbd from '$lib/components/Kbd.svelte';
  import { isWritten } from '$lib/exam-session';
  import { optionLetter } from '$lib/questions';
  import { examKey } from '$lib/shortcuts';
  import ConfidencePicker from './ConfidencePicker.svelte';
  import type { QuestionPublic } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';
  import { composeStaged, splitStaged, STAGE_LABELS, STAGES } from '$lib/viva';

  let {
    question,
    number,
    selected,
    text = '',
    confidence = undefined,
    disabled = false,
    onchoose,
    ontext,
    onconfidence = () => {}
  }: {
    question: QuestionPublic;
    number: number;
    selected: number | undefined;
    text?: string;
    confidence?: number | undefined;
    disabled?: boolean;
    onchoose: (option: number | null) => void;
    ontext: (text: string) => void;
    onconfidence?: (level: number | null) => void;
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

  // A–E pick an option, 1–3 set confidence (ignored while typing, e.g. in a written answer).
  function onKey(event: KeyboardEvent) {
    if (disabled) return;
    const action = examKey(event, question.options.length, written);
    if (!action) return;
    event.preventDefault();
    if (action.kind === 'choose') onchoose(action.option);
    else onconfidence(confidence === action.level ? null : action.level);
  }
</script>

<svelte:window onkeydown={onKey} />

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
      <legend class="sr-only">Options (keys A to {optionLetter(question.options.length - 1)})</legend>
      <div class="flex flex-col gap-2">
        {#each question.options as option, i (i)}
          <label
            class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-[0.9375rem] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]
              {selected === i ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}"
          >
            <input
              type="radio"
              name="option-{question.id}"
              value={i}
              checked={selected === i}
              aria-keyshortcuts={optionLetter(i)}
              onchange={() => onchoose(i)}
              class="sr-only"
            />
            <span class="font-mono text-xs font-semibold text-muted">{optionLetter(i)}</span>
            <span class="text-ink">{option}</span>
          </label>
        {/each}
      </div>
    </fieldset>
    <p class="mt-2 hidden text-xs text-muted sm:block">
      Press <Kbd key="A" />–<Kbd key={optionLetter(question.options.length - 1)} /> to choose.
    </p>
    {#if selected !== undefined && !disabled}
      <button type="button" class="link mt-3 text-sm" onclick={() => onchoose(null)}>Clear answer</button>
    {/if}
  {/if}
  <ConfidencePicker level={confidence} {disabled} onchange={onconfidence} />
</article>
