// Radial layout for the concept-page graph (ADR 0030). Pure, no dependency:
// the concept sits in the centre, 1-hop neighbours on an inner ring, and each
// 2-hop neighbour in the angular sector of the 1-hop node that reaches it.

export interface GraphNodeIn {
  id: string;
  name: string;
  concept_type: string;
  depth: number;
}

export interface GraphEdgeIn {
  source: string;
  target: string;
  relation: string;
}

export interface PlacedNode extends GraphNodeIn {
  x: number;
  y: number;
  label: string;
}

export interface PlacedEdge extends GraphEdgeIn {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface GraphLayout {
  size: number;
  nodes: PlacedNode[];
  edges: PlacedEdge[];
}

const LABEL_MAX = 22;

export function shortLabel(name: string, max = LABEL_MAX): string {
  const clean = name.trim();
  return clean.length <= max ? clean : `${clean.slice(0, max - 1).trimEnd()}…`;
}

function neighbours(edges: GraphEdgeIn[]): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const { source, target } of edges) {
    if (!out.has(source)) out.set(source, new Set());
    if (!out.has(target)) out.set(target, new Set());
    out.get(source)!.add(target);
    out.get(target)!.add(source);
  }
  return out;
}

const round = (value: number) => Math.round(value * 10) / 10;

function place(node: GraphNodeIn, cx: number, cy: number, radius: number, angle: number): PlacedNode {
  return { ...node, x: round(cx + radius * Math.cos(angle)), y: round(cy + radius * Math.sin(angle)), label: shortLabel(node.name) };
}

/** Deterministic radial positions; unknown or unreachable nodes are dropped. */
export function radialLayout(center: string, nodes: GraphNodeIn[], edges: GraphEdgeIn[], size = 420): GraphLayout {
  const c = size / 2;
  const root = nodes.find((n) => n.id === center);
  if (!root) return { size, nodes: [], edges: [] };
  const byName = (a: GraphNodeIn, b: GraphNodeIn) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
  const ring1 = nodes.filter((n) => n.depth === 1 && n.id !== center).sort(byName);
  const ring2 = nodes.filter((n) => n.depth === 2 && n.id !== center).sort(byName);
  const r1 = ring2.length ? size * 0.24 : size * 0.36;
  const r2 = size * 0.42;
  const placed = new Map<string, PlacedNode>([[root.id, { ...root, x: c, y: c, label: shortLabel(root.name) }]]);
  const step = ring1.length ? (2 * Math.PI) / ring1.length : 0;
  ring1.forEach((node, i) => placed.set(node.id, place(node, c, c, r1, i * step - Math.PI / 2)));
  const links = neighbours(edges);
  const groups = new Map<string, GraphNodeIn[]>();
  for (const node of ring2) {
    const parent = ring1.find((p) => links.get(node.id)?.has(p.id));
    if (!parent) continue;
    groups.set(parent.id, [...(groups.get(parent.id) ?? []), node]);
  }
  ring1.forEach((parent, i) => {
    const children = groups.get(parent.id) ?? [];
    const base = i * step - Math.PI / 2;
    children.forEach((child, j) => {
      const offset = children.length === 1 ? 0 : (j / (children.length - 1) - 0.5) * step * 0.8;
      placed.set(child.id, place(child, c, c, r2, base + offset));
    });
  });
  const placedEdges: PlacedEdge[] = [];
  for (const edge of edges) {
    const a = placed.get(edge.source);
    const b = placed.get(edge.target);
    if (a && b && a !== b) placedEdges.push({ ...edge, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  }
  return { size, nodes: [...placed.values()], edges: placedEdges };
}

/** Roving focus for arrow keys over the graph's nodes (wraps around). */
export function nextFocus(index: number, key: string, count: number): number {
  if (count <= 0) return -1;
  if (key === 'ArrowRight' || key === 'ArrowDown') return (index + 1) % count;
  if (key === 'ArrowLeft' || key === 'ArrowUp') return (index - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return index;
}
