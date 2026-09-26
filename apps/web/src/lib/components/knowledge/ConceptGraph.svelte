<script lang="ts">
  import { nextFocus, radialLayout } from '$lib/graph-layout';
  import type { GraphOut } from '$lib/types/knowledge';

  let { graph }: { graph: GraphOut } = $props();
  let layout = $derived(radialLayout(graph.center, graph.nodes, graph.edges));
  let hovered = $state<string | null>(null);
  let links: (HTMLAnchorElement | null)[] = $state([]);

  function onkey(event: KeyboardEvent, index: number) {
    const next = nextFocus(index, event.key, layout.nodes.length);
    if (next !== index && next >= 0) {
      event.preventDefault();
      links[next]?.focus();
    }
  }

  const touches = (edge: { source: string; target: string }) =>
    hovered !== null && (edge.source === hovered || edge.target === hovered);
</script>

{#if layout.nodes.length > 1}
  <figure class="panel overflow-hidden p-2">
    <svg
      viewBox="0 0 {layout.size} {layout.size}"
      class="mx-auto block h-auto w-full max-w-[34rem]"
      role="group"
      aria-label="Concept graph: {layout.nodes.length - 1} related concepts within two links. Use arrow keys to move between concepts."
    >
      <g aria-hidden="true">
        {#each layout.edges as edge, i (i)}
          <line
            x1={edge.x1}
            y1={edge.y1}
            x2={edge.x2}
            y2={edge.y2}
            class={touches(edge) ? 'stroke-accent' : 'stroke-line-strong'}
            stroke-width={touches(edge) ? 2 : 1}
          >
            <title>{edge.relation.replace(/_/g, ' ')}</title>
          </line>
        {/each}
      </g>
      {#each layout.nodes as node, i (node.id)}
        {@const center = node.id === graph.center}
        <a
          bind:this={links[i]}
          href="/knowledge/{node.id}"
          aria-label="{node.name}, {node.concept_type}{center ? ', this concept' : `, ${node.depth} link${node.depth > 1 ? 's' : ''} away`}"
          aria-current={center ? 'page' : undefined}
          class="group outline-none"
          onkeydown={(event) => onkey(event, i)}
          onmouseenter={() => (hovered = node.id)}
          onmouseleave={() => (hovered = null)}
          onfocus={() => (hovered = node.id)}
          onblur={() => (hovered = null)}
        >
          <circle
            cx={node.x}
            cy={node.y}
            r={center ? 9 : node.depth === 1 ? 6 : 4.5}
            class="{center ? 'fill-accent' : node.depth === 1 ? 'fill-info' : 'fill-muted'} stroke-surface group-focus-visible:stroke-ink"
            stroke-width="2"
          />
          <text
            x={node.x}
            y={node.y + (center ? 22 : 16)}
            text-anchor="middle"
            class="fill-ink-2 font-sans text-[0.625rem] group-hover:fill-ink group-focus-visible:fill-ink {center ? 'font-semibold' : ''}"
            >{node.label}</text
          >
        </a>
      {/each}
    </svg>
    <figcaption class="px-2 pb-1 text-center text-xs text-muted">
      Links come only from your own sources. Select a concept to open it.
    </figcaption>
  </figure>
{:else}
  <p class="text-sm text-muted">No linked concepts yet.</p>
{/if}
