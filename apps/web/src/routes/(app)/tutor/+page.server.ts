import { fail, redirect } from '@sveltejs/kit';
import { loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { failureMessage } from '$lib/server/client';
import { sourceDetail } from '$lib/server/library';
import { ask, getThread, listThreads } from '$lib/server/tutor';
import { parseFocus, validateAsk } from '$lib/tutor-stream';
import type { Actions, PageServerLoad } from './$types';

/** `?source=&page=` from the Reader's "Ask about this page" (ADR 0025), with its title. */
async function loadFocus(event: Parameters<PageServerLoad>[0]) {
  const focus = parseFocus(event.url.searchParams.get('source'), event.url.searchParams.get('page'));
  if (!focus) return null;
  const detail = await sourceDetail(event, focus.source_id);
  return detail.state === 'ok' ? { ...focus, title: detail.data.title } : null;
}

export const load: PageServerLoad = async (event) => {
  const param = event.url.searchParams.get('thread');
  const threadId = param && isUuid(param) ? param : null;
  const [threads, thread, focus] = await Promise.all([
    listThreads(event),
    threadId ? getThread(event, threadId) : Promise.resolve(null),
    loadFocus(event)
  ]);
  return {
    problem: loadProblem(threads),
    threads: threads.state === 'ok' ? threads.data : [],
    thread: thread?.state === 'ok' ? thread.data : null,
    threadProblem: param && (!threadId || thread?.state !== 'ok') ? 'That thread could not be opened.' : null,
    focus
  };
};

export const actions: Actions = {
  ask: async (event) => {
    const form = await event.request.formData();
    const question = String(form.get('question') ?? '').trim();
    const input = validateAsk(question, String(form.get('thread_id') ?? ''), form.get('allow_web'), {
      image_id: form.get('image_id'),
      focus_source: form.get('focus_source'),
      focus_page: form.get('focus_page')
    });
    if (!input.ok) return fail(400, { error: input.error, question });
    const result = await ask(event, input.body);
    if (result.state !== 'ok') {
      const status = result.state === 'error' ? result.status : 503;
      return fail(status, { error: failureMessage(result), question });
    }
    const focus = input.body.focus;
    const keep = focus ? `&source=${encodeURIComponent(focus.source_id)}&page=${focus.page_no}` : '';
    redirect(303, `/tutor?thread=${encodeURIComponent(result.data.thread_id)}${keep}`);
  }
};
