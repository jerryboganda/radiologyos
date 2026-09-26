<script lang="ts">
  import type { Drafts } from '$lib/tutor-drafts';

  // Text streamed while the tutor writes (ADR 0025). It is unverified and has
  // no citations yet, so it is shown muted, under an explicit label, and is
  // replaced by the judged answer (unsupported sentences removed).
  let { drafts }: { drafts: Drafts } = $props();
  let sources = $derived(drafts.sources.filter((s) => s.trim()));
  let web = $derived(drafts.web.filter((s) => s.trim()));
</script>

{#if sources.length || web.length}
  <div class="panel border-dashed p-4 sm:p-5" aria-live="off" data-testid="tutor-draft">
    <p class="label !text-warn">Draft · not yet checked · sentences its sources do not support will be removed</p>
    <div class="mt-2 flex flex-col gap-2 text-[0.9375rem] leading-relaxed text-ink-2 italic">
      {#each sources as text, i (i)}<p>{text}</p>{/each}
    </div>
    {#if web.length}
      <div class="mt-3 rounded-xl border border-web/30 bg-web-soft/40 p-3">
        <p class="label !text-web">Draft from the web · not from your library</p>
        <div class="mt-1 flex flex-col gap-2 text-[0.9375rem] leading-relaxed text-ink-2 italic">
          {#each web as text, i (i)}<p>{text}</p>{/each}
        </div>
      </div>
    {/if}
  </div>
{/if}
