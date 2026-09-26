// Upload queue state: validates, then uploads two files at a time.
import { errorDetail } from '$lib/api-state';
import type { UploadResponse } from '$lib/types/library';
import { checkUpload, uploadErrorMessage } from '$lib/upload';
import { sendFile } from '$lib/upload-xhr';

export type ItemState = 'queued' | 'uploading' | 'done' | 'duplicate' | 'error' | 'rejected' | 'cancelled';

export interface QueueItem {
  key: number;
  name: string;
  size: number;
  progress: number;
  state: ItemState;
  message: string | null;
  sourceId: string | null;
}

const CONCURRENCY = 2;

export class UploadQueue {
  items = $state<QueueItem[]>([]);
  #files = new Map<number, File>();
  #controllers = new Map<number, AbortController>();
  #next = 1;
  #active = 0;
  private onUploaded: () => void;

  constructor(onUploaded: () => void) {
    this.onUploaded = onUploaded;
  }

  add(files: Iterable<File>): void {
    for (const file of files) {
      const check = checkUpload(file.name, file.size);
      const key = this.#next++;
      this.items.push({
        key,
        name: file.name,
        size: file.size,
        progress: 0,
        state: check.ok ? 'queued' : 'rejected',
        message: check.ok ? check.warning : check.reason,
        sourceId: null
      });
      if (check.ok) this.#files.set(key, file);
    }
    this.#pump();
  }

  cancel(key: number): void {
    this.#controllers.get(key)?.abort();
    const item = this.items.find((i) => i.key === key);
    if (item?.state === 'queued') {
      item.state = 'cancelled';
      this.#files.delete(key);
    }
  }

  clearFinished(): void {
    this.items = this.items.filter((i) => i.state === 'queued' || i.state === 'uploading');
  }

  get busy(): boolean {
    return this.items.some((i) => i.state === 'queued' || i.state === 'uploading');
  }

  #pump(): void {
    while (this.#active < CONCURRENCY) {
      const item = this.items.find((i) => i.state === 'queued');
      if (!item) return;
      void this.#upload(item);
    }
  }

  async #upload(item: QueueItem): Promise<void> {
    const file = this.#files.get(item.key);
    if (!file) return;
    this.#active += 1;
    item.state = 'uploading';
    const controller = new AbortController();
    this.#controllers.set(item.key, controller);
    const outcome = await sendFile(file, (p) => (item.progress = p), controller.signal);
    this.#controllers.delete(item.key);
    this.#files.delete(item.key);
    this.#active -= 1;
    this.#settle(item, outcome.status, outcome.body);
    this.#pump();
  }

  #settle(item: QueueItem, status: number, body: unknown): void {
    if (status === -1) {
      item.state = 'cancelled';
      return;
    }
    if (status >= 200 && status < 300) {
      const result = body as UploadResponse;
      item.progress = 1;
      item.sourceId = result?.source_id ?? null;
      item.state = result?.duplicate ? 'duplicate' : 'done';
      item.message = result?.duplicate ? 'Already in your library.' : 'Uploaded — processing started.';
      this.onUploaded();
      return;
    }
    item.state = 'error';
    item.message = uploadErrorMessage(status, errorDetail(body, ''));
  }
}
