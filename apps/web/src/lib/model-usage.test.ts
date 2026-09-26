import assert from 'node:assert/strict';
import { test } from 'node:test';
import { byAgent, isModelUsage, openAlerts, successRate, windowExhausted } from './model-usage.ts';
import type { ModelUsage, ModelUsageRow } from './types/admin.ts';

function row(overrides: Partial<ModelUsageRow> = {}): ModelUsageRow {
  return {
    day: '2026-09-26',
    agent: 'tutor_answer/v3',
    backend: 'claude_code',
    calls: 4,
    ok: 3,
    errors: 1,
    usage_limit: 0,
    rejected: 0,
    input_tokens: 1000,
    output_tokens: 200,
    cost_usd: 0.5,
    avg_duration_ms: 12000,
    ...overrides
  };
}

function usage(overrides: Partial<ModelUsage> = {}): ModelUsage {
  return {
    window_days: 14,
    calls: 10,
    errors: 1,
    usage_limit: 2,
    rejected: 1,
    input_tokens: 5000,
    output_tokens: 900,
    cost_usd: 1.25,
    usage_limit_last_hour: 0,
    rows: [row()],
    alerts: [],
    ...overrides
  };
}

test('isModelUsage accepts the API shape and rejects malformed bodies', () => {
  assert.equal(isModelUsage(usage()), true);
  assert.equal(isModelUsage(null), false);
  assert.equal(isModelUsage({ ...usage(), calls: 'ten' }), false);
  assert.equal(isModelUsage({ ...usage(), rows: [{ ...row(), agent: 3 }] }), false);
  assert.equal(isModelUsage({ ...usage(), alerts: [{ id: 'x', level: 'green', created_at: 'now' }] }), false);
  assert.equal(isModelUsage({ ...usage(), cost_usd: Number.NaN }), false);
});

test('byAgent sums days and backends per agent, busiest first', () => {
  const agents = byAgent([
    row(),
    row({ day: '2026-09-25', backend: 'mistral', calls: 2, errors: 0, rejected: 1, usage_limit: 1 }),
    row({ agent: 'page_parse/v2', calls: 9, errors: 0 })
  ]);
  assert.deepEqual(
    agents.map((a) => [a.agent, a.calls, a.failures, a.usageLimit]),
    [
      ['page_parse/v2', 9, 0, 0],
      ['tutor_answer/v3', 6, 2, 1]
    ]
  );
  assert.equal(agents[1].tokens, 2400);
  assert.equal(agents[1].costUsd, 1);
});

test('successRate counts errors, usage limits, and rejections as failures', () => {
  assert.equal(successRate(usage()), 0.6);
  assert.equal(successRate(usage({ calls: 0 })), null);
});

test('window state and open alerts', () => {
  assert.equal(windowExhausted(usage()), false);
  assert.equal(windowExhausted(usage({ usage_limit_last_hour: 3 })), true);
  const open = openAlerts(
    usage({
      alerts: [
        { id: 'a', level: 'amber', created_at: '2026-09-20T08:00:00Z', acknowledged_at: '2026-09-20T09:00:00Z' },
        { id: 'b', level: 'amber', created_at: '2026-09-21T08:00:00Z', acknowledged_at: null },
        { id: 'c', level: 'amber', created_at: '2026-09-22T08:00:00Z', acknowledged_at: null }
      ]
    })
  );
  assert.deepEqual(
    open.map((a) => a.id),
    ['c', 'b']
  );
});
