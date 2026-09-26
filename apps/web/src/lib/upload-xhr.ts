// Browser upload with progress. XMLHttpRequest is used because fetch() does
// not report upload progress. The request goes to the SvelteKit server
// (same origin, session cookie), which streams it to the API.
export interface UploadOutcome {
  status: number;
  body: unknown;
}

export function sendFile(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal
): Promise<UploadOutcome> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append('file', file, file.name);
    xhr.open('POST', '/library/upload');
    xhr.responseType = 'json';
    xhr.setRequestHeader('accept', 'application/json');
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.response });
    xhr.onerror = () => resolve({ status: 0, body: null });
    xhr.onabort = () => resolve({ status: -1, body: null });
    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}
