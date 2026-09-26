// Lay out a grounded tutor answer (ADR 0028): headings from `section`, tables
// from segments that set both `row` and `column` (a comparison or a DDx), and
// prose for everything else. Every cell is still a cited segment. Pure for
// node --test.
import type { Segment } from './types/tutor.ts';

export interface TableRow {
  label: string;
  /** One list of segments per column, in column order (empty = not covered). */
  cells: Segment[][];
}

export type AnswerBlock =
  | { kind: 'heading'; text: string }
  | { kind: 'text'; segment: Segment }
  | { kind: 'table'; columns: string[]; rows: TableRow[] };

interface Grid {
  columns: string[];
  rows: Map<string, Map<string, Segment[]>>;
}

function isCell(segment: Segment): boolean {
  return segment.origin === 'sources' && Boolean(segment.row?.trim()) && Boolean(segment.column?.trim());
}

function toTable(grid: Grid): AnswerBlock {
  const rows = [...grid.rows].map(([label, cells]) => ({
    label,
    cells: grid.columns.map((column) => cells.get(column) ?? [])
  }));
  return { kind: 'table', columns: grid.columns, rows };
}

export function layoutAnswer(segments: Segment[]): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let section = '';
  let grid: Grid | null = null;
  const flush = () => {
    if (grid) blocks.push(toTable(grid));
    grid = null;
  };
  for (const segment of segments) {
    const heading = segment.origin === 'sources' ? (segment.section ?? '').trim() : '';
    if (heading && heading !== section) {
      flush();
      blocks.push({ kind: 'heading', text: heading });
      section = heading;
    }
    if (!isCell(segment)) {
      flush();
      blocks.push({ kind: 'text', segment });
      continue;
    }
    const current: Grid = grid ?? { columns: [], rows: new Map() };
    grid = current;
    const row = segment.row!.trim();
    const column = segment.column!.trim();
    if (!current.columns.includes(column)) current.columns.push(column);
    const cells = current.rows.get(row) ?? new Map<string, Segment[]>();
    current.rows.set(row, cells);
    cells.set(column, [...(cells.get(column) ?? []), segment]);
  }
  flush();
  return blocks;
}

/** Where a quiz hand-off goes: question generation, pre-filled with the topic. */
export function quizHref(topic: string): string {
  return `/questions?topic=${encodeURIComponent(topic.trim().slice(0, 200))}`;
}
