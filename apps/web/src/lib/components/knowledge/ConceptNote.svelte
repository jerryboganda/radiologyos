<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { footnotes, noteBadge, noteSections } from '$lib/concept-note';
  import type { ClaimOut, NoteSentence, NoteState } from '$lib/types/knowledge';

  let { info, claims }: { info: NoteState | null; claims: ClaimOut[] } = $props();
  let busy = $state(false);
  let note = $derived(info?.note ?? null);
  let sections = $derived(note ? noteSections(note.body) : []);
  let notes = $derived(note ? footnotes(note.body, claims) : { numbers: new Map<string, number>(), list: [] });
  let badge = $derived(info ? noteBadge(info) : null);
  const TONES = { ok: 'border-ok/40 bg-ok-soft text-ok', warn: 'border-warn/40 bg-warn-soft text-warn', muted: 'border-line bg-surface-2 text-ink-2' };

  function refs(sentence: NoteSentence): number[] {
    return sentence.claim_ids.map((id) => notes.numbers.get(id) ?? 0).filter((n) => n > 0);
  }

  const submit = () => {
    busy = true;
    return async ({ update }: { update: () => Promise<void> }) => {
      await update();
      busy = false;
    };
  };
</script>

{#snippet sentenceView(sentence: NoteSentence)}
  <span>{sentence.text}</span>{#each refs(sentence) as n (n)}<sup class="ml-0.5"
      ><a class="font-mono text-[0.6875rem] text-accent no-underline hover:underline" href="#note-ref-{n}" aria-label="Citation {n}">[{n}]</a></sup
    >{/each}
{/snippet}

<div class="panel p-5">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-center gap-2">
      {#if badge}<span class="rounded-lg border px-2.5 py-1 text-xs font-medium {TONES[badge.tone]}">{badge.label}</span>{/if}
      {#if note}<span class="label">v{note.version} · {note.sentences} cited sentences{note.dropped ? ` · ${note.dropped} unsupported dropped` : ''}</span>{/if}
    </div>
    <div class="flex flex-wrap gap-2">
      {#if info?.verifiable && note}
        <form method="POST" action="?/verify" use:enhance={submit}>
          <input type="hidden" name="note_id" value={note.id} />
          <button class="btn btn-primary min-h-9 px-3 py-1.5 text-sm" type="submit" disabled={busy}>Mark verified</button>
        </form>
      {/if}
      <form method="POST" action="?/synthesize" use:enhance={submit}>
        <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" type="submit" disabled={busy}>
          {note ? 'Regenerate from claims' : 'Write the note'}
        </button>
      </form>
    </div>
  </div>

  {#if !note}
    <p class="mt-3 text-sm text-muted">
      No note yet. It is written only from the claims below, and every sentence must cite one of them.
    </p>
  {:else}
    {#each sections as section (section.key)}
      <section class="mt-4" aria-label={section.title}>
        <h3 class="label mb-1.5">{section.title}</h3>
        {#each section.groups as group, g (g)}
          {#if group.heading}<p class="mt-2 text-sm font-semibold text-ink">{group.heading}</p>{/if}
          <ul class="flex flex-col gap-1.5 text-[0.9375rem] leading-relaxed text-ink">
            {#each group.sentences as sentence, i (i)}<li>{@render sentenceView(sentence)}</li>{/each}
          </ul>
        {/each}
      </section>
    {/each}
    {#if notes.list.length}
      <details class="mt-4">
        <summary class="cursor-pointer text-sm text-accent">Sources for this note ({notes.list.length} claims)</summary>
        <ol class="mt-2 flex flex-col gap-2 text-sm">
          {#each notes.list as ref (ref.claimId)}
            <li id="note-ref-{ref.n}" class="flex flex-wrap items-baseline gap-2">
              <span class="font-mono text-xs text-muted">[{ref.n}]</span>
              <span class="text-ink-2">{ref.claim?.statement ?? 'Claim no longer available'}</span>
              {#if ref.claim}<CitationChip citation={ref.claim.citation} />{/if}
            </li>
          {/each}
        </ol>
      </details>
    {/if}
  {/if}
</div>
