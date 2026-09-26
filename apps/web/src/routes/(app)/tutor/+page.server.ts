import { fail, redirect } from '@sveltejs/kit';
import { loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { failureMessage } from '$lib/server/client';
import { ask, getThread, listThreads } from '$lib/server/tutor';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const param = event.url.searchParams.get('thread');
  const threadId = param && isUuid(param) ? param : null;
  const [threads, thread] = await Promise.all([
    listThreads(event),
    threadId ? getThread(event, threadId) : Promise.resolve(null)
  ]);
  return {
    problem: loadProblem(threads),
    threads: threads.state === 'ok' ? threads.data : [],
    thread: thread?.state === 'ok' ? thread.data : null,
    threadProblem: param && (!threadId || thread?.state !== 'ok') ? 'That thread could not be opened.' : null
  };
};

export const actions: Actions = {
  ask: async (event) => {
    const form = await event.request.formData();
    const question = String(form.get('question') ?? '').trim();
    const rawThread = String(form.get('thread_id') ?? '');
    const allowWeb = form.get('allow_web') === 'on';
    if (question.length < 3) return fail(400, { error: 'Ask a full question.', question });
    if (question.length > 2000) return fail(400, { error: 'Keep questions under 2,000 characters.', question });
    const threadId = isUuid(rawThread) ? rawThread : null;
    const result = await ask(event, { question, thread_id: threadId, allow_web: allowWeb });
    if (result.state !== 'ok') {
      const status = result.state === 'error' ? result.status : 503;
      return fail(status, { error: failureMessage(result), question });
    }
    redirect(303, `/tutor?thread=${encodeURIComponent(result.data.thread_id)}`);
  }
};
