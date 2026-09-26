// Cloze and image cards (ADR 0029): rendering helpers and the generator form. Pure for node --test.
import type { Parsed } from './questions.ts';
import type { CardOut, CardType, KnowledgeCardsIn } from './types/study.ts';

/** The blank the API puts where a cloze card's key term was. */
export const BLANK = '_____';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ClozePart = { blank: false; text: string } | { blank: true };

/** Split a cloze front into text runs and blanks, so blanks can be styled. */
export function clozeParts(front: string): ClozePart[] {
  const parts: ClozePart[] = [];
  front.split(BLANK).forEach((text, i) => {
    if (i > 0) parts.push({ blank: true });
    if (text) parts.push({ blank: false, text });
  });
  return parts;
}

/** A cloze back is "answer\n\nstatement\n\nEvidence: …"; the first paragraph is the answer. */
export function clozeAnswer(back: string): { answer: string; rest: string } {
  const [answer = '', ...rest] = back.split(/\n\s*\n/);
  return { answer: answer.trim(), rest: rest.join('\n\n').trim() };
}

export function cardType(card: Pick<CardOut, 'card_type'>): CardType {
  return card.card_type === 'cloze' || card.card_type === 'image' ? card.card_type : 'basic';
}

export const CARD_TYPE_LABELS: Record<CardType, string> = { basic: 'Recall', cloze: 'Cloze', image: 'Image' };

export function parseKnowledgeCardsForm(form: FormData): Parsed<KnowledgeCardsIn> {
  const kind = String(form.get('kind') ?? '');
  if (kind !== 'cloze' && kind !== 'image') return { ok: false, error: 'Choose cloze or image cards.' };
  const max = Number(form.get('max_cards') ?? 20);
  if (!Number.isInteger(max) || max < 1 || max > 50) return { ok: false, error: 'Choose between 1 and 50 cards.' };
  const sourceId = String(form.get('source_id') ?? '').trim();
  if (sourceId && !UUID.test(sourceId)) return { ok: false, error: 'Choose a source.' };
  const topic = String(form.get('topic') ?? '').trim().slice(0, 200);
  return {
    ok: true,
    value: { kind, max_cards: max, source_id: sourceId || null, topic: topic.length >= 2 ? topic : null }
  };
}

export function knowledgeSummary(kind: string, made: number, skipped: number): string {
  const noun = kind === 'image' ? 'image card' : 'cloze card';
  const from = kind === 'image' ? 'described figures' : 'verified claims';
  if (made === 0) return `No new ${noun}s: nothing left to card from your ${from}${skipped ? ` (${skipped} skipped)` : ''}.`;
  return `Created ${made} ${noun}${made === 1 ? '' : 's'} from your ${from}${skipped ? ` (${skipped} skipped: no citable key term)` : ''}.`;
}
