import { fail } from '@sveltejs/kit';
import { failureMessage } from '$lib/server/client';
import { ask, getThread, listThreads } from '$lib/server/tutor';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const threadId = event.url.searchParams.get('thread');
  const [threads, thread] = await Promise.all([
    listThreads(event),
    threadId ? getThread(event, threadId) : Promise.resolve(null)
  ]);
  return {
    online: threads.state === 'ok',
    threads: threads.state === 'ok' ? threads.data : [],
    thread: thread?.state === 'ok' ? thread.data : null
  };
};

export const actions: Actions = {
  ask: async (event) => {
    const form = await event.request.formData();
    const question = String(form.get('question') ?? '').trim();
    const threadId = String(form.get('thread_id') ?? '') || null;
    const allowWeb = form.get('allow_web') === 'on';
    if (question.length < 3) return fail(400, { error: 'Ask a full question.', question });
    if (question.length > 2000) return fail(400, { error: 'Keep questions under 2,000 characters.', question });
    const result = await ask(event, question, threadId, allowWeb);
    if (result.state !== 'ok') {
      return fail(503, { error: failureMessage(result, 'The tutor is not online yet.'), question });
    }
    return { answer: result.data };
  }
};
