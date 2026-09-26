<script lang="ts">
  import { enhance } from '$app/forms';
  // Legacy global styles, loaded only here. Links inside reload the page so
  // these globals never leak into the Tailwind app (see ADR 0017).
  import './legacy-base.css';
  import './preview.css';
  import type { ActionData, PageData } from './$types';

  type PreviewAction = {
    error?: string;
    result?: {
      chunks?: { text: string; score: number; citation: { page_no: number } }[];
      answer?: string;
      grounding?: string;
      citations?: unknown[];
    };
  };

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let actionData = $derived(form as PreviewAction | null);
  let searchQuery = $state('');
  let tutorQuery = $state('');
  let searchHits = $derived(actionData?.result?.chunks ?? []);
  let tutorAnswer = $derived(actionData?.result?.answer ?? '');
</script>

<svelte:head>
  <title>radbrain · non-release preview</title>
  <meta name="description" content="Synthetic non-release radbrain preview." />
</svelte:head>

<div class="preview-shell" data-sveltekit-reload>
  <header class="preview-header">
    <div>
      <a class="brand" href="/">radbrain</a>
      <p class="preview-kicker">Non-release preview</p>
    </div>
    <nav aria-label="Preview navigation">
      <a href="#library">Library</a>
      <a href="#plan">Plan</a>
      <a href="#tutor">Tutor</a>
      <a href="#assessment">Assessment</a>
    </nav>
  </header>

  <div class="preview-notice" role="status">
    <strong>Synthetic local preview.</strong>
    <span>Not staging evidence, clinical guidance, exam validation, billing, or a release candidate.</span>
  </div>

  {#if !data.enabled}
    <section class="empty-state">
      <h1>Preview unavailable</h1>
      <p>Sign in through the local development session and enable <code>PREVIEW_ENABLED=true</code>.</p>
    </section>
  {:else}
    {#if actionData?.error}<p class="error" role="alert">{actionData.error}</p>{/if}

    <main class="preview-main">
      <section class="intro-block">
        <p class="eyebrow">M1–M7 preview workspace</p>
        <h1>Study flows, clearly marked as synthetic.</h1>
        <p>Use the panels below to exercise the local preview contract. Every source, citation, plan, question, and score is fixture-backed.</p>
      </section>

      <div class="preview-grid">
        <section id="library" class="preview-panel panel-wide">
          <div class="panel-heading">
            <div><p class="eyebrow">M1 · Library</p><h2>Synthetic sources</h2></div>
            <span class="status-chip">Local state</span>
          </div>
          <form method="POST" action="?/createSource" use:enhance class="stack-form">
            <label for="source-title">Source title</label>
            <input id="source-title" name="title" required maxlength="500" placeholder="Synthetic notes" />
            <label for="source-content">Text fixture</label>
            <textarea id="source-content" name="content" required maxlength="200000" rows="5" placeholder="Paste synthetic text only"></textarea>
            <button class="button" type="submit">Add preview source</button>
          </form>
          {#if data.sources.length}
            <ul class="record-list">
              {#each data.sources as source}
                <li><strong>{source.title}</strong><span>{source.status} · {source.page_count} pages · {source.figure_count} figures</span></li>
              {/each}
            </ul>
          {:else}
            <div class="empty-state compact"><p>No synthetic sources yet.</p></div>
          {/if}
        </section>

        <section class="preview-panel">
          <div class="panel-heading"><div><p class="eyebrow">M1 · Search</p><h2>Lexical preview</h2></div></div>
          <form method="POST" action="?/search" use:enhance class="stack-form">
            <label for="search-query">Search query</label>
            <input id="search-query" name="query" bind:value={searchQuery} required placeholder="ground-glass" />
            <button class="button secondary-button" type="submit">Search sources</button>
          </form>
          {#if searchHits.length}
            <ul class="result-list">
              {#each searchHits as hit}
                <li><p>{hit.text}</p><small>Score {hit.score.toFixed(2)} · p. {hit.citation.page_no}</small></li>
              {/each}
            </ul>
          {:else}
            <p class="muted">Search returns cited chunks only; no generated summary is emitted.</p>
          {/if}
        </section>

        <section id="plan" class="preview-panel">
          <div class="panel-heading"><div><p class="eyebrow">M4 · Planner</p><h2>Exam-date plan</h2></div></div>
          {#if data.plan}
            <dl class="metric-list">
              <div><dt>Phase</dt><dd>{data.plan.phase}</dd></div>
              <div><dt>Days remaining</dt><dd>{data.plan.days_remaining}</dd></div>
              <div><dt>Version</dt><dd>{data.plan.plan_version}</dd></div>
            </dl>
            <p class="muted">{data.plan.notice}</p>
          {:else}
            <form method="POST" action="?/onboard" use:enhance class="stack-form">
              <label for="exam-date">Exam date</label>
              <input id="exam-date" name="exam_date" type="date" required />
              <label for="hours-per-week">Hours per week</label>
              <input id="hours-per-week" name="hours_per_week" type="number" min="1" max="40" value="8" />
              <button class="button secondary-button" type="submit">Create synthetic plan</button>
            </form>
          {/if}
          {#if data.today}
            <div class="today-box"><strong>Today</strong><span>{data.today.phase} · {data.today.blocks.length} blocks · viva omitted in preview</span></div>
          {/if}
        </section>

        <section id="tutor" class="preview-panel">
          <div class="panel-heading"><div><p class="eyebrow">M3 · Tutor</p><h2>Grounded mock answer</h2></div></div>
          <form method="POST" action="?/ask" use:enhance class="stack-form">
            <label for="tutor-query">Ask your synthetic sources</label>
            <input id="tutor-query" name="query" bind:value={tutorQuery} required placeholder="What is in the fixture?" />
            <button class="button secondary-button" type="submit">Ask preview tutor</button>
          </form>
          {#if tutorAnswer}
            <div class="answer-box"><p>{tutorAnswer}</p><small>{actionData?.result?.grounding} · {actionData?.result?.citations?.length ?? 0} citations</small></div>
          {:else}
            <p class="muted">No uncited tutor answer is emitted. A miss says so explicitly.</p>
          {/if}
        </section>

        <section id="assessment" class="preview-panel panel-wide">
          <div class="panel-heading"><div><p class="eyebrow">M5 · Assessment</p><h2>Synthetic SBA preview</h2></div><a class="text-link" href="/api/preview?resource=questions">Open question contract</a></div>
          {#if data.questions.length}
            <ol class="question-list">
              {#each data.questions as question}
                <li><strong>{question.stem}</strong><span>{question.curriculum_code} · {question.options.length} options · citations required</span></li>
              {/each}
            </ol>
          {:else}
            <p class="muted">Questions are created on first preview request.</p>
          {/if}
        </section>

        <section class="preview-panel">
          <div class="panel-heading"><div><p class="eyebrow">M6–M7 · Operations</p><h2>Explicit boundaries</h2></div></div>
          <ul class="boundary-list">
            <li>Billing: mock test-mode status only.</li>
            <li>Export: tenant-local Markdown fixture.</li>
            <li>Release audit: blocked until staging evidence exists.</li>
          </ul>
          <div class="operation-links"><a class="text-link" href="/api/preview?resource=markdown">Preview Markdown</a><a class="text-link" href="/api/preview?resource=audit">Release audit</a></div>
        </section>
      </div>
    </main>
  {/if}
</div>
