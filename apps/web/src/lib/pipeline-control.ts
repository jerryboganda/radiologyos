// Library processing card (ADR 0037): pause state, progress, and items waiting
// for the owner's OK to use Claude Opus. Pure for node --test.
import type { AwaitingPart, PipelineStatus, PipelineTone } from './types/admin.ts';

const COUNT_KEYS = ['pages', 'jobs', 'knowledge_units', 'awaiting_owner'] as const;

/** Friendly provider names; anything else is shown with a capital first letter. */
const PROVIDERS: Record<string, string> = { chatgpt: 'ChatGPT', claude: 'Claude', openai: 'OpenAI', voyage: 'Voyage' };

/** What each agent's waiting items are, in owner words: [one, many]. */
const AWAITING_NOUNS: Record<string, [string, string]> = {
  page_parse: ['page', 'pages'],
  image_case: ['figure', 'figures'],
  knowledge_extract: ['note', 'notes']
};
const AWAITING_ORDER = Object.keys(AWAITING_NOUNS);

const finiteCount = (value: unknown): boolean => typeof value === 'number' && Number.isFinite(value) && value >= 0;

function isCounts(value: unknown): value is Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return Object.values(value).every(finiteCount);
}

/** Shape check so an unexpected body can never break the Settings page. */
export function isPipelineStatus(value: unknown): value is PipelineStatus {
  if (!value || typeof value !== 'object') return false;
  const status = value as Record<string, unknown>;
  return (
    (status.paused === null || typeof status.paused === 'string') &&
    (status.resume_at === null || (typeof status.resume_at === 'number' && Number.isFinite(status.resume_at))) &&
    (status.provider === null || typeof status.provider === 'string') &&
    COUNT_KEYS.every((key) => isCounts(status[key]))
  );
}

const sum = (counts: Record<string, number>): number => Object.values(counts).reduce((total, n) => total + n, 0);
const count = (counts: Record<string, number>, key: string): number => counts[key] ?? 0;
const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

export function providerName(provider: string | null): string {
  if (!provider) return 'model';
  return PROVIDERS[provider.toLowerCase()] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** "HH:MM" (24-hour) for an epoch-seconds instant, in the given time zone (default: the runtime's). */
export function clockTime(epochSeconds: number, timeZone?: string): string {
  const format = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
  return format.format(new Date(epochSeconds * 1000));
}

/** Books still being worked on, plus pages still waiting to be read. */
export function hasWork(status: PipelineStatus): boolean {
  return count(status.jobs, 'queued') + count(status.jobs, 'running') + count(status.pages, 'pending') > 0;
}

export interface PipelineSummary {
  text: string;
  tone: PipelineTone;
  paused: boolean;
}

/** The one-line state in plain English. */
export function pipelineSummary(status: PipelineStatus, timeZone?: string): PipelineSummary {
  if (status.paused === 'manual') return { text: 'Paused by you', tone: 'warn', paused: true };
  if (status.paused === 'quota') {
    const when = status.resume_at === null ? '' : `, resumes about ${clockTime(status.resume_at, timeZone)}`;
    return { text: `Paused — ${providerName(status.provider)} quota reached${when}`, tone: 'warn', paused: true };
  }
  if (status.paused) return { text: 'Paused', tone: 'warn', paused: true };
  if (hasWork(status)) return { text: 'Running', tone: 'ok', paused: false };
  return { text: 'Idle — nothing waiting', tone: 'idle', paused: false };
}

export interface PipelineProgress {
  pagesRead: number;
  pagesTotal: number;
  pagesFailed: number;
  booksActive: number;
  booksFailed: number;
  unitsDone: number;
  unitsFailed: number;
}

export function pipelineProgress(status: PipelineStatus): PipelineProgress {
  return {
    pagesRead: count(status.pages, 'done'),
    pagesTotal: sum(status.pages),
    pagesFailed: count(status.pages, 'failed'),
    booksActive: count(status.jobs, 'queued') + count(status.jobs, 'running'),
    booksFailed: count(status.jobs, 'failed'),
    unitsDone: count(status.knowledge_units, 'succeeded'),
    unitsFailed: count(status.knowledge_units, 'failed')
  };
}

export function awaitingTotal(status: PipelineStatus): number {
  return sum(status.awaiting_owner);
}

/** Waiting items by kind (pages, figures, notes, then anything else), zero counts dropped. */
export function awaitingParts(status: PipelineStatus): AwaitingPart[] {
  const agents = Object.keys(status.awaiting_owner).filter((agent) => count(status.awaiting_owner, agent) > 0);
  const rank = (agent: string): number => {
    const index = AWAITING_ORDER.indexOf(agent);
    return index === -1 ? AWAITING_ORDER.length : index;
  };
  agents.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  return agents.map((agent) => {
    const n = count(status.awaiting_owner, agent);
    const [one, many] = AWAITING_NOUNS[agent] ?? ['other item', 'other items'];
    return { agent, count: n, text: plural(n, one, many) };
  });
}

/** "12 pages, 3 figures, 1 note"; '' when nothing is waiting. */
export function awaitingText(status: PipelineStatus): string {
  return awaitingParts(status)
    .map((part) => part.text)
    .join(', ');
}

/** The approve form's explicit quota acknowledgement. */
export function confirmsQuota(form: FormData): boolean {
  return form.get('confirm') === 'yes';
}
