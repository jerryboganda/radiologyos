<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { IMAGE_TYPES, imageProblem, uploadedId } from '$lib/tutor-image';

  // Attach one spotter/unknown-case image to the next question (ADR 0025).
  // The file uploads at once to /tutor/image (private, owner-only storage);
  // only its id rides with the question. The input has no name, so the form
  // itself never posts file bytes.
  let { imageId = $bindable(''), disabled = false }: { imageId?: string; disabled?: boolean } = $props();
  let preview = $state<string | null>(null);
  let uploading = $state(false);
  let error = $state<string | null>(null);
  let input = $state<HTMLInputElement | null>(null);

  export function clear() {
    if (preview) URL.revokeObjectURL(preview);
    preview = null;
    imageId = '';
    if (input) input.value = '';
  }

  async function choose(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    error = null;
    if (!file) return;
    const problem = imageProblem(file.type, file.size, file.name);
    if (problem) {
      error = problem;
      clear();
      return;
    }
    const body = new FormData();
    body.append('file', file);
    uploading = true;
    try {
      const response = await fetch('/tutor/image', { method: 'POST', body });
      const data: unknown = await response.json().catch(() => null);
      const id = response.ok ? uploadedId(data) : null;
      if (!id) {
        const detail = data && typeof data === 'object' ? (data as Record<string, unknown>).detail : null;
        error = typeof detail === 'string' ? detail : `The image could not be uploaded (${response.status}).`;
        clear();
        return;
      }
      clear();
      imageId = id;
      preview = URL.createObjectURL(file);
    } catch {
      error = 'The image could not be uploaded; check your connection.';
      clear();
    } finally {
      uploading = false;
    }
  }
</script>

<div class="flex flex-wrap items-center gap-2">
  <label class="btn btn-ghost min-h-9 cursor-pointer px-2.5 py-1.5 text-sm {disabled || uploading ? 'pointer-events-none opacity-50' : ''}">
    <Icon name="image" size={16} />
    <span>{uploading ? 'Uploading…' : imageId ? 'Replace image' : 'Attach image'}</span>
    <input
      bind:this={input}
      type="file"
      accept={IMAGE_TYPES.join(',')}
      class="sr-only"
      disabled={disabled || uploading}
      onchange={choose}
    />
  </label>
  {#if preview && imageId}
    <span class="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 p-1 pr-2 text-xs text-ink-2">
      <img src={preview} alt="Attached for this question" class="h-9 w-12 rounded bg-stage object-cover" />
      Image attached
      <button type="button" class="text-muted hover:text-ink" aria-label="Remove the attached image" onclick={clear}>
        <Icon name="x" size={14} />
      </button>
    </span>
  {/if}
  {#if error}<span class="text-xs text-warn" role="alert">{error}</span>{/if}
  <span class="w-full text-[0.6875rem] text-muted">PNG, JPEG or WebP up to 20 MB. No DICOM, and no patient identifiers.</span>
</div>
