import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  bannerMessage,
  capShare,
  formatTokens,
  formatUsd,
  isAdminRole,
  isEmbeddingUsage,
  MAX_ACK_IDS,
  parseAckIds,
  safeReturnPath,
  selectBanner,
  sortAlerts
} from './admin-usage.ts';
import type { EmbeddingUsage, UsageAlert } from './types/admin.ts';

const RED_ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';
const AMBER_ID = '7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f';

function alert(overrides: Partial<UsageAlert> = {}): UsageAlert {
  return { id: AMBER_ID, level: 'amber', created_at: '2026-09-20T08:00:00Z', acknowledged_at: null, ...overrides };
}

function usage(overrides: Partial<EmbeddingUsage> = {}): EmbeddingUsage {
  return {
    document_model: 'voyage-4-large',
    query_model: 'voyage-4-nano',
    tokens_used: 3_200_000,
    hard_cap_tokens: 195_000_000,
    warn_tokens: 150_000_000,
    free_tier_tokens: 200_000_000,
    free_tier_remaining: 196_800_000,
    status: 'ok',
    list_price_usd_equivalent: 0.58,
    billed_estimate_usd: 0,
    alerts: [],
    ...overrides
  };
}

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [k, v] of entries) data.append(k, v);
  return data;
}

test('token counts read as compact figures', () => {
  assert.equal(formatTokens(950), '950');
  assert.equal(formatTokens(1000), '1K');
  assert.equal(formatTokens(12_500), '12.5K');
  assert.equal(formatTokens(3_200_000), '3.2M');
  assert.equal(formatTokens(12_345_678), '12.3M');
  assert.equal(formatTokens(99_960_000), '100M');
  assert.equal(formatTokens(150_000_000), '150M');
  assert.equal(formatTokens(195_000_000), '195M');
  assert.equal(formatTokens(999_950), '1M');
  assert.equal(formatTokens(1_234_567_890), '1.2B');
  assert.equal(formatTokens(-1), '—');
  assert.equal(formatTokens(Number.NaN), '—');
  assert.equal(formatTokens(null), '—');
});

test('share of the cap is clamped for the meter', () => {
  assert.equal(capShare(0, 195_000_000), 0);
  assert.equal(capShare(97_500_000, 195_000_000), 0.5);
  assert.ok(Math.abs(capShare(150_000_000, 195_000_000) - 0.769) < 0.001);
  assert.equal(capShare(250_000_000, 195_000_000), 1);
  assert.equal(capShare(10, 0), 0);
  assert.equal(capShare(Number.NaN, 10), 0);
});

test('money shows cents and never goes negative', () => {
  assert.equal(formatUsd(0), '$0.00');
  assert.equal(formatUsd(1234.5), '$1,234.50');
  assert.equal(formatUsd(-3), '$0.00');
  assert.equal(formatUsd(undefined), '—');
});

test('only org admins and superadmins are treated as admins', () => {
  assert.equal(isAdminRole('org_admin'), true);
  assert.equal(isAdminRole('superadmin'), true);
  assert.equal(isAdminRole('student'), false);
  assert.equal(isAdminRole('editor'), false);
  assert.equal(isAdminRole(undefined), false);
});

test('usage bodies are shape-checked before the shell trusts them', () => {
  assert.equal(isEmbeddingUsage(usage()), true);
  assert.equal(isEmbeddingUsage(usage({ alerts: [alert()] })), true);
  assert.equal(isEmbeddingUsage({ ...usage(), status: 'purple' }), false);
  assert.equal(isEmbeddingUsage({ ...usage(), tokens_used: '5' }), false);
  assert.equal(isEmbeddingUsage({ ...usage(), alerts: null }), false);
  assert.equal(isEmbeddingUsage({ ...usage(), alerts: [{ id: 1 }] }), false);
  assert.equal(isEmbeddingUsage('<html>'), false);
  assert.equal(isEmbeddingUsage(null), false);
});

test('red banner needs red status and an unacknowledged red alert', () => {
  const red = alert({ id: RED_ID, level: 'red' });
  assert.deepEqual(selectBanner(usage({ status: 'red', alerts: [alert(), red] })), {
    level: 'red',
    alertIds: [RED_ID],
    hardCapTokens: 195_000_000,
    warnTokens: 150_000_000
  });
  const acked = { ...red, acknowledged_at: '2026-09-21T08:00:00Z' };
  assert.equal(selectBanner(usage({ status: 'red', alerts: [alert(), acked] })), null);
});

test('amber banner needs amber status and an unacknowledged amber alert', () => {
  assert.equal(selectBanner(usage({ status: 'amber', alerts: [alert()] }))?.level, 'amber');
  assert.equal(selectBanner(usage({ status: 'amber', alerts: [alert({ acknowledged_at: '2026-09-21T08:00:00Z' })] })), null);
  assert.equal(selectBanner(usage({ status: 'amber', alerts: [alert({ id: RED_ID, level: 'red' })] })), null);
  assert.equal(selectBanner(usage({ status: 'ok', alerts: [alert()] })), null);
  assert.equal(selectBanner(null), null);
});

test('banner copy states the cap and the consequence', () => {
  const base = { alertIds: [RED_ID], hardCapTokens: 195_000_000, warnTokens: 150_000_000 };
  assert.equal(
    bannerMessage({ ...base, level: 'red' }),
    'Embedding budget exhausted — Voyage API embedding is stopped at 195M tokens. New documents stay keyword-searchable only.'
  );
  assert.equal(bannerMessage({ ...base, level: 'amber' }), 'Embedding usage above 150M of the 195M hard cap.');
});

test('alert history is newest first', () => {
  const older = alert({ id: AMBER_ID, created_at: '2026-09-01T00:00:00Z' });
  const newer = alert({ id: RED_ID, level: 'red', created_at: '2026-09-25T00:00:00Z' });
  assert.deepEqual(sortAlerts([older, newer]).map((a) => a.id), [RED_ID, AMBER_ID]);
});

test('acknowledge forms carry distinct alert UUIDs only', () => {
  assert.deepEqual(parseAckIds(form([['id', RED_ID], ['id', RED_ID], ['id', AMBER_ID]])), [RED_ID, AMBER_ID]);
  assert.equal(parseAckIds(form([])), null);
  assert.equal(parseAckIds(form([['id', 'not-a-uuid']])), null);
  assert.equal(parseAckIds(form([['id', RED_ID], ['id', '../admin']])), null);
  const many = Array.from({ length: MAX_ACK_IDS + 1 }, (_, i) => ['id', `${String(i).padStart(8, '0')}-0000-4000-8000-000000000000`]);
  assert.equal(parseAckIds(form(many as [string, string][])), null);
});

test('no-JS acknowledge returns only to same-origin paths', () => {
  assert.equal(safeReturnPath('/library?source=1#top'), '/library?source=1#top');
  assert.equal(safeReturnPath('/settings'), '/settings');
  assert.equal(safeReturnPath('//evil.example/x'), '/');
  assert.equal(safeReturnPath('/\\evil.example'), '/');
  assert.equal(safeReturnPath('/\t/evil.example'), '/');
  assert.equal(safeReturnPath('https://evil.example'), '/');
  assert.equal(safeReturnPath('javascript:alert(1)'), '/');
  assert.equal(safeReturnPath(null), '/');
});
