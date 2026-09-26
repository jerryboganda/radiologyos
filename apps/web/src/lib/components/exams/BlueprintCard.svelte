<script lang="ts">
  import { enhance } from '$app/forms';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { itemsText, markingText, mixText } from '$lib/blueprints';
  import type { BlueprintOut } from '$lib/types/assessment';

  let { blueprint }: { blueprint: BlueprintOut } = $props();
  let busy = $state(false);
  const submit = () => {
    busy = true;
    return async ({ update }: { update: () => Promise<void> }) => {
      await update();
      busy = false;
    };
  };
</script>

<li class="panel p-5">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 class="font-semibold text-ink">{blueprint.title}</h2>
      <p class="label mt-0.5">{blueprint.id} · {itemsText(blueprint)}</p>
    </div>
    <StatusBadge status={blueprint.approved ? 'approved' : 'pending'} />
  </div>
  <p class="mt-3 text-sm text-ink-2">{markingText(blueprint)}</p>
  <p class="mt-1 text-sm text-ink-2">Mix: {mixText(blueprint)}</p>
  {#if blueprint.unverified.length}
    <p class="mt-2 text-sm text-warn">Unverified from public sources: {blueprint.unverified.join(', ').replace(/_/g, ' ')}.</p>
  {/if}
  <p class="mt-2 text-sm text-muted">{blueprint.notes}</p>
  {#if Object.keys(blueprint.overrides).length}
    <p class="label mt-2">Your changes: {Object.keys(blueprint.overrides).join(', ').replace(/_/g, ' ')}</p>
  {/if}
  <details class="mt-3">
    <summary class="cursor-pointer text-sm text-ink-2">Sources and changes</summary>
    <ul class="mt-2 flex flex-col gap-1 text-sm">
      {#each blueprint.sources as url (url)}<li><a class="break-all text-ink-2 underline underline-offset-2" href={url} rel="noreferrer noopener" target="_blank">{url}</a></li>{/each}
    </ul>
    <form method="POST" action="?/override" class="mt-3 grid gap-3 sm:grid-cols-3" use:enhance={submit}>
      <input type="hidden" name="blueprint_id" value={blueprint.id} />
      <label class="block"><span class="label">Minutes</span>
        <input name="duration_minutes" type="number" min="1" max="600" placeholder={String(blueprint.duration_minutes)} class="field mt-1.5 font-mono" /></label>
      <label class="block"><span class="label">Penalty per wrong SBA (0–1)</span>
        <input name="penalty" type="number" min="0" max="1" step="0.05" placeholder={String(blueprint.negative_marking.penalty)} class="field mt-1.5 font-mono" /></label>
      <label class="block"><span class="label">Pass mark %</span>
        <input name="pass_mark_percent" type="number" min="0" max="100" step="0.5" placeholder={blueprint.pass_mark_percent === null ? 'not published' : String(blueprint.pass_mark_percent)} class="field mt-1.5 font-mono" /></label>
      <div class="sm:col-span-3"><button class="btn btn-ghost" type="submit" disabled={busy}>Save changes (blank restores defaults)</button></div>
    </form>
  </details>
  {#if !blueprint.approved}
    <form method="POST" action="?/approve" class="mt-3" use:enhance={submit}>
      <input type="hidden" name="blueprint_id" value={blueprint.id} />
      <input type="hidden" name="content_hash" value={blueprint.content_hash} />
      <button class="btn btn-primary" type="submit" disabled={busy}>Approve this format</button>
    </form>
  {/if}
</li>
