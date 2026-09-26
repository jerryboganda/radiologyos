// Keyboard shortcuts (spec: 1–4 card ratings, A–E options). Pure for node --test.
//
// Shortcuts never fire while the user is typing (text inputs, textareas, selects,
// contenteditable) or when a modifier is held, so they cannot clash with browser
// or assistive-technology keys. Radio buttons and plain buttons are not "typing".

export interface KeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  isComposing?: boolean;
  target?: unknown;
}

const NON_TEXT_INPUTS = new Set(['radio', 'checkbox', 'button', 'submit', 'reset', 'range', 'color']);

/** True when `target` is a place where keys type text. */
export function isTypingTarget(target: unknown): boolean {
  if (!target || typeof target !== 'object') return false;
  const el = target as { tagName?: unknown; type?: unknown; isContentEditable?: unknown };
  if (el.isContentEditable === true) return true;
  const tag = typeof el.tagName === 'string' ? el.tagName.toUpperCase() : '';
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = typeof el.type === 'string' ? el.type.toLowerCase() : 'text';
  return !NON_TEXT_INPUTS.has(type);
}

/**
 * True for controls that Space/Enter already activate natively (buttons, links,
 * summaries): those keys are left to the browser there, so a focused control
 * elsewhere on the page is never hijacked.
 */
export function isActivatable(target: unknown): boolean {
  if (!target || typeof target !== 'object') return false;
  const tag = (target as { tagName?: unknown }).tagName;
  return typeof tag === 'string' && ['BUTTON', 'A', 'SUMMARY'].includes(tag.toUpperCase());
}

const ACTIVATION_KEYS = new Set([' ', 'Enter']);

/** Keys that must be left alone: typing, IME composition, or any modifier held. */
export function ignoreKey(event: KeyLike): boolean {
  if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return true;
  if (ACTIVATION_KEYS.has(event.key) && isActivatable(event.target)) return true;
  return isTypingTarget(event.target);
}

export type ReviewAction = { kind: 'reveal' } | { kind: 'rate'; rating: 1 | 2 | 3 | 4 };

/** Card review: Space (or Enter) reveals; once revealed, 1–4 rate Again/Hard/Good/Easy. */
export function reviewKey(event: KeyLike, revealed: boolean): ReviewAction | null {
  if (ignoreKey(event)) return null;
  if (!revealed) return event.key === ' ' || event.key === 'Enter' ? { kind: 'reveal' } : null;
  const rating = Number(event.key);
  return event.key.length === 1 && rating >= 1 && rating <= 4 ? { kind: 'rate', rating: rating as 1 | 2 | 3 | 4 } : null;
}

/** A–E (either case) → option index 0–4, within `count` options; null otherwise. */
export function optionKey(event: KeyLike, count: number): number | null {
  if (ignoreKey(event) || event.key.length !== 1) return null;
  const index = event.key.toUpperCase().charCodeAt(0) - 65;
  return index >= 0 && index < Math.min(count, 5) ? index : null;
}

export type SbaAction = { kind: 'choose'; option: number } | { kind: 'confidence'; level: 1 | 2 | 3 } | { kind: 'submit' };

/** SBA item: A–E choose, 1–3 set confidence, Enter submits (or moves on after feedback). */
export function sbaKey(event: KeyLike, count: number): SbaAction | null {
  if (ignoreKey(event)) return null;
  if (event.key === 'Enter') return { kind: 'submit' };
  const option = optionKey(event, count);
  if (option !== null) return { kind: 'choose', option };
  const level = Number(event.key);
  return event.key.length === 1 && level >= 1 && level <= 3 ? { kind: 'confidence', level: level as 1 | 2 | 3 } : null;
}

export type ExamAction = { kind: 'choose'; option: number } | { kind: 'confidence'; level: 1 | 2 | 3 };

/**
 * Timed exam item (ADR 0029), the same modifier-free scheme as the session SBA
 * block: A–E choose (option items only), 1–3 set confidence. Letters and digits
 * never overlap, and neither fires while typing a written answer.
 */
export function examKey(event: KeyLike, count: number, written: boolean): ExamAction | null {
  if (ignoreKey(event) || event.key.length !== 1) return null;
  const level = Number(event.key);
  if (level >= 1 && level <= 3) return { kind: 'confidence', level: level as 1 | 2 | 3 };
  if (written) return null;
  const option = optionKey(event, count);
  return option === null ? null : { kind: 'choose', option };
}

/** `aria-keyshortcuts` values and the visible hint text for each surface. */
export const HINTS = {
  reveal: { aria: 'Space', label: 'Space' },
  rating: (n: number) => ({ aria: String(n), label: String(n) }),
  option: (i: number) => ({ aria: String.fromCharCode(65 + i), label: String.fromCharCode(65 + i) }),
  confidence: (n: number) => ({ aria: String(n), label: String(n) }),
  submit: { aria: 'Enter', label: 'Enter' }
} as const;
