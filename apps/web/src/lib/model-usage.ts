// Model-call ledger card (ADR 0032). Pure for node --test.
import type { AgentUsage, ModelUsage, ModelUsageRow, UsageAlert } from './types/admin.ts';

const ROW_NUMBERS = ['calls', 'ok', 'errors', 'usage_limit', 'rejected', 'input_tokens', 'output_tokens', 'cost_usd', 'avg_duration_ms'] as const;
const TOTAL_NUMBERS = [
  'window_days',
  'calls',
  'errors',
  'usage_limit',
  'rejected',
  'input_tokens',
  'output_tokens',
  'cost_usd',
  'usage_limit_last_hour'
] as const;

const finite = (value: unknown): boolean => typeof value === 'number' && Number.isFinite(value);

function isRow(value: unknown): value is ModelUsageRow {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return typeof row.day === 'string' && typeof row.agent === 'string' && typeof row.backend === 'string' && ROW_NUMBERS.every((key) => finite(row[key]));
}

function isAlert(value: unknown): value is UsageAlert {
  if (!value || typeof value !== 'object') return false;
  const alert = value as Record<string, unknown>;
  return (
    typeof alert.id === 'string' &&
    (alert.level === 'amber' || alert.level === 'red') &&
    typeof alert.created_at === 'string' &&
    (alert.acknowledged_at == null || typeof alert.acknowledged_at === 'string')
  );
}

/** Shape check so an unexpected body can never break the Settings page. */
export function isModelUsage(value: unknown): value is ModelUsage {
  if (!value || typeof value !== 'object') return false;
  const usage = value as Record<string, unknown>;
  return (
    TOTAL_NUMBERS.every((key) => finite(usage[key])) &&
    Array.isArray(usage.rows) &&
    usage.rows.every(isRow) &&
    Array.isArray(usage.alerts) &&
    usage.alerts.every(isAlert)
  );
}

/** Per-agent totals, busiest first; ties by name for a stable table. */
export function byAgent(rows: ModelUsageRow[]): AgentUsage[] {
  const totals = new Map<string, AgentUsage>();
  for (const row of rows) {
    const entry = totals.get(row.agent) ?? { agent: row.agent, calls: 0, failures: 0, usageLimit: 0, tokens: 0, costUsd: 0 };
    entry.calls += row.calls;
    entry.failures += row.errors + row.rejected;
    entry.usageLimit += row.usage_limit;
    entry.tokens += row.input_tokens + row.output_tokens;
    entry.costUsd += row.cost_usd;
    totals.set(row.agent, entry);
  }
  return [...totals.values()].sort((a, b) => b.calls - a.calls || a.agent.localeCompare(b.agent));
}

/** Share of attempts that succeeded, in [0, 1]; null with no calls. */
export function successRate(usage: Pick<ModelUsage, 'calls' | 'errors' | 'usage_limit' | 'rejected'>): number | null {
  if (usage.calls <= 0) return null;
  const failed = usage.errors + usage.usage_limit + usage.rejected;
  return Math.min(Math.max((usage.calls - failed) / usage.calls, 0), 1);
}

/** The usage window is exhausted right now when usage-limit errors arrived this hour. */
export function windowExhausted(usage: ModelUsage): boolean {
  return usage.usage_limit_last_hour > 0;
}

/** Unacknowledged usage-limit alerts, newest first. */
export function openAlerts(usage: ModelUsage): UsageAlert[] {
  return usage.alerts.filter((alert) => !alert.acknowledged_at).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}
