<script lang="ts">
  import { invalidate } from '$app/navigation';
  import Icon from '$lib/components/Icon.svelte';
  import { formatBytes } from '$lib/format';
  import { ACCEPT_ATTRIBUTE } from '$lib/upload';
  import { UploadQueue, type ItemState } from './upload-queue.svelte';

  const queue = new UploadQueue(() => void invalidate('app:library'));
  let dragging = $state(false);
  let input: HTMLInputElement | undefined = $state();

  const TONE: Record<ItemState, string> = {
    queued: 'text-muted',
    uploading: 'text-warn',
    done: 'text-ok',
    duplicate: 'text-info',
    error: 'text-danger',
    rejected: 'text-danger',
    cancelled: 'text-muted'
  };

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragging = false;
    if (event.dataTransfer?.files.length) queue.add(event.dataTransfer.files);
  }

  function onPick(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    if (target.files?.length) queue.add(target.files);
    target.value = '';
  }
</script>

<section aria-labelledby="upload-heading" class="panel p-4 sm:p-5">
  <h2 id="upload-heading" class="sr-only">Upload sources</h2>
  <div
    role="presentation"
    class="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors
      {dragging ? 'border-accent bg-accent-soft' : 'border-line-strong bg-surface-2/50'}"
    ondragenter={(e) => {
      e.preventDefault();
      dragging = true;
    }}
    ondragover={(e) => e.preventDefault()}
    ondragleave={() => (dragging = false)}
    ondrop={onDrop}
  >
    <span class="flex h-11 w-11 items-center justify-center rounded-full bg-surface text-accent ring-1 ring-line">
      <Icon name="upload" />
    </span>
    <div>
      <p class="font-medium text-ink">Drop study files here</p>
      <p class="mt-0.5 text-sm text-muted">PDF, DOCX, PPTX, JPEG, PNG · several at once</p>
    </div>
    <button type="button" class="btn btn-primary" onclick={() => input?.click()}>Choose files</button>
    <input bind:this={input} type="file" multiple accept={ACCEPT_ATTRIBUTE} class="sr-only" onchange={onPick} tabindex="-1" />
    <p class="max-w-md text-xs leading-relaxed text-muted">
      Files over 100 MB are blocked by Cloudflare on the public site — split them or upload on the local network.
      DICOM is not accepted; export key images as PNG/JPEG. Uploads stay private to you.
    </p>
  </div>

  {#if queue.items.length}
    <ul class="mt-4 divide-y divide-line" aria-live="polite">
      {#each queue.items as item (item.key)}
        <li class="flex items-center gap-3 py-2.5">
          <Icon name="file" size={18} class="text-muted" />
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline justify-between gap-3">
              <p class="truncate text-sm font-medium text-ink">{item.name}</p>
              <span class="shrink-0 font-mono text-[0.6875rem] {TONE[item.state]}">
                {item.state === 'uploading' ? `${Math.round(item.progress * 100)}%` : item.state}
              </span>
            </div>
            {#if item.state === 'uploading' || item.state === 'queued'}
              <div class="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2">
                <div class="h-full rounded-full bg-accent transition-[width]" style="width: {item.progress * 100}%"></div>
              </div>
            {/if}
            <p class="mt-0.5 text-xs text-muted">
              {formatBytes(item.size)}{#if item.message}<span class={TONE[item.state]}> · {item.message}</span>{/if}
              {#if item.sourceId}· <a class="link" href="/library/{item.sourceId}">Open</a>{/if}
            </p>
          </div>
          {#if item.state === 'uploading' || item.state === 'queued'}
            <button type="button" class="rounded-md p-1.5 text-muted hover:text-danger" aria-label="Cancel {item.name}" onclick={() => queue.cancel(item.key)}>
              <Icon name="x" size={16} />
            </button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if !queue.busy}
      <button type="button" class="mt-2 text-xs text-muted hover:text-ink" onclick={() => queue.clearFinished()}>Clear list</button>
    {/if}
  {/if}
</section>
