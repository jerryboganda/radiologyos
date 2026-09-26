// Admin API contract: embedding budget meter and its alerts
// (GET /v1/admin/embedding-usage, POST /v1/admin/alerts/{id}/ack).
// org_admin / superadmin only; the API answers 403 for every other role.
export type UsageStatus = 'ok' | 'amber' | 'red';
export type AlertLevel = 'amber' | 'red';

export interface UsageAlert {
  id: string;
  level: AlertLevel;
  created_at: string;
  acknowledged_at: string | null;
}

export interface EmbeddingUsage {
  /** Voyage model used for document embeddings (billed against the free tier). */
  document_model: string;
  /** Query embeddings run locally, so they are free. */
  query_model: string;
  tokens_used: number;
  /** Embedding stops at this many tokens (below the free tier). */
  hard_cap_tokens: number;
  /** The amber alert fires at this many tokens. */
  warn_tokens: number;
  free_tier_tokens: number;
  free_tier_remaining: number;
  status: UsageStatus;
  /** What the tokens used would cost at Voyage list price (informational). */
  list_price_usd_equivalent: number;
  /** What Voyage would actually bill beyond the free tier (normally 0). */
  billed_estimate_usd: number;
  alerts: UsageAlert[];
  /** The reranker's own ledger (ADR 0028); absent when no reranker is configured. */
  rerank?: RerankUsage | null;
}

/** Voyage rerank usage: its free tier and hard cap are separate from embeddings. */
export interface RerankUsage {
  model: string;
  tokens_used: number;
  hard_cap_tokens: number;
  warn_tokens: number;
  free_tier_tokens: number;
  free_tier_remaining: number;
  status: UsageStatus;
  list_price_usd_equivalent: number;
  billed_estimate_usd: number;
  alerts: UsageAlert[];
}

/** The app-shell banner: the level shown and every unacknowledged alert it covers. */
export interface AdminBanner {
  /** Which budget the banner is about; embedding when absent. */
  kind?: 'embedding' | 'rerank';
  level: AlertLevel;
  alertIds: string[];
  hardCapTokens: number;
  warnTokens: number;
}

// Model-call ledger (GET /v1/admin/model-usage, ADR 0032). Counts and names only.
export interface ModelUsageRow {
  day: string;
  agent: string;
  backend: string;
  calls: number;
  ok: number;
  errors: number;
  usage_limit: number;
  rejected: number;
  input_tokens: number;
  output_tokens: number;
  /** Transport-reported cost; for subscription calls an API-price equivalent. */
  cost_usd: number;
  avg_duration_ms: number;
}

export interface ModelUsage {
  window_days: number;
  calls: number;
  errors: number;
  usage_limit: number;
  rejected: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  usage_limit_last_hour: number;
  rows: ModelUsageRow[];
  alerts: UsageAlert[];
}

/** One agent's totals across the window, for the Settings table. */
export interface AgentUsage {
  agent: string;
  calls: number;
  failures: number;
  usageLimit: number;
  tokens: number;
  costUsd: number;
}
