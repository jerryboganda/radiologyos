<script lang="ts">
  import type { DdxBranch } from '$lib/concept-note';

  let { name, branches, numbers }: { name: string; branches: DdxBranch[]; numbers: Map<string, number> } = $props();
</script>

{#if branches.length === 0}
  <p class="text-sm text-muted">No differentials are cited or linked for this concept yet.</p>
{:else}
  <div class="panel p-5">
    <p class="font-semibold text-ink">{name}</p>
    <ul class="mt-2 flex flex-col gap-3 border-l-2 border-line pl-4" aria-label="Differential diagnoses of {name}">
      {#each branches as branch (branch.conceptId ?? branch.name)}
        <li class="relative before:absolute before:top-3 before:-left-4 before:w-3 before:border-t-2 before:border-line">
          <p class="flex flex-wrap items-center gap-2">
            {#if branch.conceptId}
              <a class="link font-medium" href="/knowledge/{branch.conceptId}">{branch.name}</a>
            {:else}
              <span class="font-medium text-ink">{branch.name}</span>
            {/if}
            {#if branch.fromGraph}<span class="label">graph link · no cited discriminator yet</span>{/if}
          </p>
          {#if branch.discriminators.length}
            <ul class="mt-1 flex list-disc flex-col gap-1 pl-5 text-sm text-ink-2">
              {#each branch.discriminators as sentence, i (i)}
                <li>
                  {sentence.text}{#each sentence.claim_ids as id (id)}{#if numbers.get(id)}<sup class="ml-0.5"
                        ><a class="font-mono text-[0.6875rem] text-accent no-underline hover:underline" href="#note-ref-{numbers.get(id)}"
                          >[{numbers.get(id)}]</a
                        ></sup
                      >{/if}{/each}
                </li>
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}
