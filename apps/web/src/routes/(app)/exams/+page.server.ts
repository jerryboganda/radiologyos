import { fail, redirect, type Cookies } from '@sveltejs/kit';
import { parseRecentExams, RECENT_EXAMS_COOKIE, withRecentExam } from '$lib/exam-session';
import { parseExamForm } from '$lib/questions';
import { createExam, getExam } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

// The API has no "list my exams" route yet, so this browser remembers the exam
// IDs it created (IDs only; the API still authorises every read).
function remember(cookies: Cookies, secure: boolean, ids: string[]) {
  cookies.set(RECENT_EXAMS_COOKIE, ids.join(','), {
    path: '/exams',
    httpOnly: true,
    sameSite: 'lax',
    secure,
    maxAge: 60 * 60 * 24 * 90
  });
}

export const load: PageServerLoad = async (event) => {
  const ids = parseRecentExams(event.cookies.get(RECENT_EXAMS_COOKIE));
  const results = await Promise.all(ids.map((id) => getExam(event, id)));
  const exams = results.flatMap((r) =>
    r.state === 'ok'
      ? [
          {
            id: r.data.id,
            mode: r.data.mode,
            status: r.data.status,
            started_at: r.data.started_at,
            questions: r.data.questions.length,
            percent: r.data.result?.percent ?? null
          }
        ]
      : []
  );
  return { exams };
};

export const actions: Actions = {
  create: async (event) => {
    const parsed = parseExamForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await createExam(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result) });
    const ids = withRecentExam(parseRecentExams(event.cookies.get(RECENT_EXAMS_COOKIE)), result.data.id);
    remember(event.cookies, event.url.protocol === 'https:', ids);
    redirect(303, `/exams/${result.data.id}`);
  }
};
