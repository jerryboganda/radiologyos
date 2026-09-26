// Concept-note view helpers (ADR 0030). Pure for node --test.
import type { ClaimOut, EdgeOut, NoteBody, NoteSentence, NoteState } from './types/knowledge.ts';

export interface NoteSection {
  key: string;
  title: string;
  groups: { heading: string | null; sentences: NoteSentence[] }[];
}

export interface Footnote {
  n: number;
  claim: ClaimOut | null;
  claimId: string;
}

export interface DdxBranch {
  name: string;
  conceptId: string | null;
  discriminators: NoteSentence[];
  fromGraph: boolean;
}

const plain = (key: string, title: string, sentences: NoteSentence[]): NoteSection => ({
  key,
  title,
  groups: [{ heading: null, sentences }]
});

/** Non-empty sections in reading order (differentials are shown as a tree). */
export function noteSections(body: NoteBody): NoteSection[] {
  const sections: NoteSection[] = [
    plain('definition', 'Definition', body.definition ?? []),
    {
      key: 'imaging',
      title: 'Imaging features',
      groups: (body.imaging ?? []).map((g) => ({ heading: g.modality, sentences: g.sentences }))
    },
    plain('pearls', 'Pearls', body.pearls ?? []),
    plain('pitfalls', 'Pitfalls', body.pitfalls ?? [])
  ];
  return sections.filter((s) => s.groups.some((g) => g.sentences.length > 0));
}

function allSentences(body: NoteBody): NoteSentence[] {
  return [
    ...(body.definition ?? []),
    ...(body.imaging ?? []).flatMap((g) => g.sentences),
    ...(body.differentials ?? []).flatMap((d) => d.discriminators),
    ...(body.pearls ?? []),
    ...(body.pitfalls ?? [])
  ];
}

/** Footnote numbers by first appearance, resolved to the concept's claims. */
export function footnotes(body: NoteBody, claims: ClaimOut[]): { numbers: Map<string, number>; list: Footnote[] } {
  const numbers = new Map<string, number>();
  const byId = new Map(claims.map((c) => [c.id, c]));
  for (const sentence of allSentences(body)) {
    for (const id of sentence.claim_ids) if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
  }
  const list = [...numbers.entries()].map(([claimId, n]) => ({ n, claimId, claim: byId.get(claimId) ?? null }));
  return { numbers, list };
}

/** Differentials from the note, then `differential_of` graph links it did not cover. */
export function ddxTree(body: NoteBody | null, edges: EdgeOut[]): DdxBranch[] {
  const branches: DdxBranch[] = (body?.differentials ?? []).map((d) => ({
    name: d.name,
    conceptId: d.concept_id ?? null,
    discriminators: d.discriminators,
    fromGraph: false
  }));
  const seen = new Set(branches.map((b) => b.conceptId ?? b.name.toLowerCase()));
  for (const edge of edges) {
    if (edge.relation !== 'differential_of' || seen.has(edge.other_id) || seen.has(edge.other_name.toLowerCase())) continue;
    seen.add(edge.other_id);
    branches.push({ name: edge.other_name, conceptId: edge.other_id, discriminators: [], fromGraph: true });
  }
  return branches;
}

export type BadgeTone = 'ok' | 'warn' | 'muted';

/** What the note's header says about trust in it. */
export function noteBadge(state: NoteState): { label: string; tone: BadgeTone } {
  if (state.state === 'missing' || !state.note) return { label: 'No note yet', tone: 'muted' };
  if (state.state === 'stale') return { label: 'Out of date: claims changed', tone: 'warn' };
  if (state.note.status === 'verified') return { label: 'Verified by you', tone: 'ok' };
  if (state.open_conflicts > 0) return { label: 'Draft · resolve conflicts to verify', tone: 'warn' };
  return { label: 'Draft · every sentence cited', tone: 'muted' };
}
