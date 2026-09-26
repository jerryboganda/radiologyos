<script lang="ts">
  import { untrack } from 'svelte';
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import { VIVA_STYLES, type VivaKind } from '$lib/types/viva';

  let {
    prefill,
    error = null
  }: {
    prefill: { kind: VivaKind; figure_id: string | null; question_id: string | null; topic: string };
    error?: string | null;
  } = $props();

  // The prefill seeds the choice once; the user may change it afterwards.
  let kind = $state<VivaKind>(untrack(() => prefill.kind));
  let starting = $state(false);
  let fromImage = $derived(Boolean(prefill.figure_id || prefill.question_id));
  const chip =
    'cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]';
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="start-heading">
  <h2 id="start-heading" class="text-xl font-semibold text-ink">Start a session</h2>
  <form
    method="POST"
    action="?/start"
    class="mt-4 grid gap-4 sm:grid-cols-2"
    use:enhance={() => {
      starting = true;
      return async ({ update }) => {
        await update();
        starting = false;
      };
    }}
  >
    <fieldset class="sm:col-span-2">
      <legend class="label">Session</legend>
      <div class="mt-1.5 flex flex-wrap gap-2">
        <label class={chip}>
          <input type="radio" name="kind" value="viva" bind:group={kind} class="sr-only" disabled={Boolean(prefill.question_id)} />
          Viva (examiner asks, escalates)
        </label>
        <label class={chip}>
          <input type="radio" name="kind" value="image_case" bind:group={kind} class="sr-only" />
          Staged image case (TOACS station)
        </label>
      </div>
    </fieldset>
    <label class="block">
      <span class="label">Format</span>
      <select name="style" class="field mt-1.5">
        {#each VIVA_STYLES as style (style.value)}<option value={style.value}>{style.label}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Topic{fromImage ? ' (optional)' : ''}</span>
      <input name="topic" maxlength="200" value={prefill.topic} required={!fromImage} placeholder="e.g. pulmonary alveolar proteinosis" class="field mt-1.5" />
    </label>
    {#if kind === 'viva'}
      <label class="block">
        <span class="label">Questions (optional)</span>
        <input name="max_turns" type="number" min="2" max="20" placeholder="Format default" class="field mt-1.5 font-mono" />
      </label>
    {/if}
    <label class="block">
      <span class="label">Time limit, minutes (optional)</span>
      <input name="time_limit_minutes" type="number" min="1" max="90" placeholder="Untimed" class="field mt-1.5 font-mono" />
    </label>
    {#if prefill.figure_id}<input type="hidden" name="figure_id" value={prefill.figure_id} />{/if}
    {#if prefill.question_id}<input type="hidden" name="question_id" value={prefill.question_id} />{/if}
    {#if fromImage}
      <p class="text-sm text-muted sm:col-span-2">
        Starting from {prefill.question_id ? 'a bank image case' : 'a figure in your library'}.
        <a class="link" href="/viva">Start from a topic instead</a>
      </p>
    {/if}
    <div class="flex items-end sm:col-span-2">
      <button class="btn btn-primary" type="submit" disabled={starting}>{starting ? 'Preparing…' : 'Start'}</button>
    </div>
  </form>
  {#if error}<div class="mt-4"><Notice tone="warn">{error}</Notice></div>{/if}
</section>
