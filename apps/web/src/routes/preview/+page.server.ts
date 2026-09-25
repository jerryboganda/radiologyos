import { env } from '$env/dynamic/private';
import { fail } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { previewFetch } from '$lib/server/preview';

type SourceView = {
  title: string;
  status: string;
  page_count: number;
  figure_count: number;
};

type PlanView = {
  phase: string;
  days_remaining: number;
  plan_version: number;
  notice: string;
};

type TodayView = {
  phase: string;
  blocks: unknown[];
};

type QuestionView = {
  question_id: string;
  stem: string;
  curriculum_code: string;
  options: string[];
};

type SearchResult = {
  chunks: { text: string; score: number; citation: { page_no: number } }[];
};

type TutorResult = {
  answer: string;
  grounding: string;
  citations: unknown[];
};

async function readJson<T>(response: Response): Promise<T | null> {
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export const load: PageServerLoad = async (event) => {
  const enabled = env.PREVIEW_ENABLED === 'true' && Boolean(event.locals.user);
  if (!enabled) return { enabled: false, sources: [], plan: null, today: null, questions: [] };
  const [sourcesResponse, planResponse, todayResponse, questionsResponse] = await Promise.all([
    previewFetch(event, 'sources'),
    previewFetch(event, 'plan'),
    previewFetch(event, 'today'),
    previewFetch(event, 'questions')
  ]);
  return {
    enabled: true,
    sources: (await readJson<SourceView[]>(sourcesResponse)) ?? [],
    plan: (await readJson<PlanView>(planResponse)) ?? null,
    today: (await readJson<TodayView>(todayResponse)) ?? null,
    questions: (await readJson<QuestionView[]>(questionsResponse)) ?? []
  };
};

export const actions: Actions = {
  createSource: async (event) => {
    const form = await event.request.formData();
    const title = String(form.get('title') ?? '');
    const content = String(form.get('content') ?? '');
    if (!title || !content) return fail(400, { error: 'Title and content are required.' });
    const response = await previewFetch(event, 'sources', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title, kind: 'note', content })
    });
    if (!response.ok) return fail(response.status, { error: 'Preview source could not be created.' });
    return { success: true };
  },
  onboard: async (event) => {
    const form = await event.request.formData();
    const response = await previewFetch(event, 'onboarding', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        exam_date: String(form.get('exam_date') ?? ''),
        hours_per_week: Number(form.get('hours_per_week') ?? 8),
        session_minutes: Number(form.get('session_minutes') ?? 60)
      })
    });
    if (!response.ok) return fail(response.status, { error: 'Preview onboarding could not be saved.' });
    return { success: true };
  },
  search: async (event) => {
    const form = await event.request.formData();
    const response = await previewFetch(event, 'search', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: String(form.get('query') ?? '') })
    });
    return { result: await readJson<SearchResult>(response) };
  },
  ask: async (event) => {
    const form = await event.request.formData();
    const response = await previewFetch(event, 'tutor', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: String(form.get('query') ?? '') })
    });
    return { result: await readJson<TutorResult>(response) };
  }
};
