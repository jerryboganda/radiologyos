import { dataOr, isKind, loadProblem } from '$lib/api-state';
import { getInsights } from '$lib/server/session';
import { getLatestReport, getProgress } from '$lib/server/study';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const [result, report, insights] = await Promise.all([getProgress(event), getLatestReport(event), getInsights(event)]);
  if (result.state !== 'ok') {
    return { progress: null, report: null, insights: null, onboarding: isKind(result, 'conflict'), problem: loadProblem(result) };
  }
  // Pass through only the fields the page renders. No pass-probability is shown
  // (CLAUDE.md "Never"), even if an API response were to include one.
  const p = result.data;
  return {
    progress: {
      exam_date: p.exam_date,
      days_remaining: p.days_remaining,
      phase: p.phase,
      retention: p.retention,
      cards: p.cards,
      due_now: p.due_now,
      new_cards: p.new_cards,
      reviews_total: p.reviews_total,
      reviews_today: p.reviews_today,
      weight_policy: p.weight_policy,
      weight_targets: p.weight_targets ?? [],
      topics: (p.topics ?? []).map((t) => ({
        code: t.code,
        title: t.title,
        mastery: t.mastery,
        band: t.band,
        accuracy: t.accuracy,
        retrievability: t.retrievability,
        coverage: t.coverage,
        cards: t.cards,
        lapses: t.lapses,
        questions: t.questions ?? 0
      })),
      notice: p.notice
    },
    // 404 until the first Monday-morning report; the card explains when it arrives.
    report: dataOr(report, null),
    // Heatmap, pace projection and calibration; the page hides them if unreachable.
    insights: insights.state === 'ok'
      ? { heatmap: insights.data.heatmap, projection: insights.data.projection, calibration: insights.data.calibration, notice: insights.data.notice }
      : null,
    onboarding: false,
    problem: null
  };
};
