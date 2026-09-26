<script lang="ts">
  import { optionLetter } from '$lib/questions';
  import type { QuestionPublic } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';

  let {
    question,
    number,
    selected,
    disabled = false,
    onchoose
  }: {
    question: QuestionPublic;
    number: number;
    selected: number | undefined;
    disabled?: boolean;
    onchoose: (option: number | null) => void;
  } = $props();
  let image = $derived(mediaUrl(question.figure_image_path));
</script>

<article class="panel p-5 sm:p-6" aria-labelledby="q-{question.id}">
  <p class="label">Question {number}{question.topic ? ` · ${question.topic}` : ''}</p>
  <p id="q-{question.id}" class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{question.stem}</p>
  {#if image}
    <div class="mt-4 overflow-hidden rounded-xl bg-stage">
      <img src={image} alt="Radiology image for question {number}" class="mx-auto max-h-[55dvh] w-auto" />
    </div>
  {/if}
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
</article>
