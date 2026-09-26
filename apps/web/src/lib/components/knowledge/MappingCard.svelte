<script lang="ts">
  import { enhance } from '$app/forms';
  import { percent } from '$lib/format';
  import type { CurriculumSystem, MappingOut } from '$lib/types/knowledge';

  let { mapping, systems }: { mapping: MappingOut; systems: CurriculumSystem[] } = $props();
  const uid = $props.id();
  let busy = $state(false);
  let code = $state('');
  let pages = $derived(mapping.page_from === mapping.page_to ? `p. ${mapping.page_from}` : `pp. ${mapping.page_from}–${mapping.page_to}`);
  let title = $derived(systems.find((s) => s.code === mapping.curriculum_code)?.title ?? mapping.curriculum_code);

  const submit = () => {
    busy = true;
    return async ({ update }: { update: (opts?: { reset?: boolean }) => Promise<void> }) => {
      await update({ reset: false });
      busy = false;
    };
  };
</script>

<li class="rounded-xl border border-line bg-surface p-4">
  <div class="flex flex-wrap items-baseline justify-between gap-2">
    <p class="font-medium text-ink">
      <span class="font-mono text-sm">{mapping.curriculum_node_id ?? mapping.curriculum_code}</span> · {title}{mapping.topic
        ? ` · ${mapping.topic}`
        : ''}
    </p>
    <span class="label">confidence {percent(mapping.confidence)}</span>
  </div>
  <p class="mt-1 text-sm text-ink-2">
    <a class="underline decoration-line underline-offset-2 hover:text-ink" href="/library/{mapping.source_id}?page={mapping.page_from}"
      >{mapping.source_title}, {pages}</a
    >
  </p>
  {#if mapping.excerpt}
    <blockquote class="mt-2 border-l-2 border-line pl-3 text-sm text-muted">{mapping.excerpt}{mapping.excerpt.length >= 400 ? '…' : ''}</blockquote>
  {/if}
  <form method="POST" action="?/decide" class="mt-3 flex flex-wrap items-end gap-2" use:enhance={submit}>
    <input type="hidden" name="mapping_id" value={mapping.id} />
    <button class="btn btn-primary min-h-9 py-1.5" type="submit" name="decision" value="accept" disabled={busy}>Accept</button>
    <button class="btn btn-ghost min-h-9 py-1.5" type="submit" name="decision" value="reject" disabled={busy}>Reject</button>
    <label class="sr-only" for="{uid}-code">Different curriculum node (system, topic, or subtopic)</label>
    <input
      id="{uid}-code"
      name="curriculum_code"
      bind:value={code}
      list="curriculum-nodes"
      maxlength="60"
      placeholder="Different node, e.g. CHEST.PULM_VASC.PE"
      class="field min-h-9 w-72 py-1.5 font-mono text-sm"
    />
    <button class="btn btn-ghost min-h-9 py-1.5" type="submit" name="decision" value="code" disabled={busy || !code}>Re-code</button>
  </form>
</li>
