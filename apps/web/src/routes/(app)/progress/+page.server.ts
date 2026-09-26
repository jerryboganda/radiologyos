import { getProgress } from '$lib/server/study';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const result = await getProgress(event);
  if (result.state !== 'ok') return { progress: null, detail: result.state === 'error' ? result.detail : null };
  // Pass through only the fields the page renders. No pass-probability is shown
  // (CLAUDE.md "Never"), even if an API response were to include one.
  const { streak_days, reviews_7d, minutes_7d, retention_30d, topics, history } = result.data;
  return {
    progress: { streak_days, reviews_7d, minutes_7d, retention_30d, topics: topics ?? [], history: history ?? [] },
    detail: null
  };
};
