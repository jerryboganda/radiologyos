// Embedding budget meter and admin alert banner. Pure for node --test.
import { isUuid } from './data-rights.ts';
import type { AdminBanner, AlertLevel, EmbeddingUsage, UsageAlert, UsageStatus } from './types/admin.ts';

/** Roles the API lets read usage. A UI hint only: the API decides (403 otherwise). */
export const ADMIN_ROLES: readonly string[] = ['org_admin', 'superadmin'];

export function isAdminRole(role: string | null | undefined): boolean {
  return typeof role === 'string' && ADMIN_ROLES.includes(role);
}

const STATUSES: readonly string[] = ['ok', 'amber', 'red'];
const NUMBERS = [
  'tokens_used',
  'hard_cap_tokens',
  'warn_tokens',
  'free_tier_tokens',
  'free_tier_remaining',
  'list_price_usd_equivalent',
  'billed_estimate_usd'
] as const;

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

/** Shape check so an unexpected body can never break the app shell. */
export function isEmbeddingUsage(value: unknown): value is EmbeddingUsage {
  if (!value || typeof value !== 'object') return false;
  const usage = value as Record<string, unknown>;
  return (
    typeof usage.document_model === 'string' &&
    typeof usage.query_model === 'string' &&
    NUMBERS.every((key) => typeof usage[key] === 'number' && Number.isFinite(usage[key])) &&
    typeof usage.status === 'string' &&
    STATUSES.includes(usage.status) &&
    Array.isArray(usage.alerts) &&
    usage.alerts.every(isAlert)
  );
}

function compact(value: number): string {
  return (value >= 100 ? value.toFixed(0) : value.toFixed(1)).replace(/\.0$/, '');
}

/** Token counts for people: 950, 12.5K, 3.2M, 195M, 1.2B. */
export function formatTokens(tokens: number | null | undefined): string {
  if (tokens == null || !Number.isFinite(tokens) || tokens < 0) return '—';
  if (tokens < 1000) return String(Math.round(tokens));
  const units = ['K', 'M', 'B'];
  let value = tokens / 1000;
  let unit = 0;
  // Promote when rounding would print "1000K".
  while (unit < units.length - 1 && Number(compact(value)) >= 1000) {
    value /= 1000;
    unit += 1;
  }
  return `${compact(value)}${units[unit]}`;
}

/** Fraction of the cap in [0, 1], for bar widths and markers. */
export function capShare(tokens: number, cap: number): number {
  if (!Number.isFinite(tokens) || !Number.isFinite(cap) || cap <= 0) return 0;
  return Math.min(Math.max(tokens / cap, 0), 1);
}

const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

export function formatUsd(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return '—';
  return USD.format(Math.max(amount, 0));
}

export const STATUS_LABEL: Record<UsageStatus, string> = {
  ok: 'Within budget',
  amber: 'Above warning',
  red: 'Embedding stopped'
};

export const ALERT_TITLE: Record<AlertLevel, string> = {
  red: 'Hard cap reached: embedding stopped',
  amber: 'Warning threshold passed'
};

/** Newest first. */
export function sortAlerts(alerts: UsageAlert[]): UsageAlert[] {
  return [...alerts].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

/**
 * The banner to show, if any: red only while the status is red, amber only
 * while it is amber, and only for alerts of that level not yet acknowledged.
 */
export function selectBanner(usage: EmbeddingUsage | null): AdminBanner | null {
  if (!usage || usage.status === 'ok') return null;
  const level = usage.status;
  const alertIds = usage.alerts.filter((alert) => alert.level === level && !alert.acknowledged_at).map((alert) => alert.id);
  if (!alertIds.length) return null;
  return { level, alertIds, hardCapTokens: usage.hard_cap_tokens, warnTokens: usage.warn_tokens };
}

export function bannerMessage(banner: AdminBanner): string {
  const cap = formatTokens(banner.hardCapTokens);
  if (banner.level === 'red') {
    return `Embedding budget exhausted — Voyage API embedding is stopped at ${cap} tokens. New documents stay keyword-searchable only.`;
  }
  return `Embedding usage above ${formatTokens(banner.warnTokens)} of the ${cap} hard cap.`;
}

export const MAX_ACK_IDS = 20;

/** Alert ids from an acknowledge form: 1..MAX_ACK_IDS distinct UUIDs, else null. */
export function parseAckIds(form: FormData): string[] | null {
  const ids = [...new Set(form.getAll('id').map((value) => String(value)))];
  return ids.length > 0 && ids.length <= MAX_ACK_IDS && ids.every(isUuid) ? ids : null;
}

const LOCAL = 'http://radbrain.invalid';

/** A same-origin path to return to after a no-JS form post; "/" when unsafe. */
export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/')) return '/';
  try {
    const url = new URL(value, LOCAL);
    return url.origin === LOCAL ? `${url.pathname}${url.search}${url.hash}` : '/';
  } catch {
    return '/';
  }
}
