<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import PushSetup from '$lib/components/settings/PushSetup.svelte';
  import DataExport from '$lib/components/settings/DataExport.svelte';
  import DeleteAccount from '$lib/components/settings/DeleteAccount.svelte';
  import EmbeddingUsage from '$lib/components/settings/EmbeddingUsage.svelte';
  import ModelUsage from '$lib/components/settings/ModelUsage.svelte';
  import InstallApp from '$lib/components/settings/InstallApp.svelte';
  import ReminderForm from '$lib/components/settings/ReminderForm.svelte';
  import ThemeToggle from '$lib/components/shell/ThemeToggle.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import { EXAM_TARGETS } from '$lib/types/study';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let timezone = $state('');
  let targets = $derived(data.profile?.exam_targets ?? ['fcps2_theory']);
  $effect(() => {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  });
</script>

<svelte:head><title>Settings · radbrain</title></svelte:head>

<PageHeader eyebrow="Settings" title="Settings" description="Appearance, your exam, reminders, and your data. Everything here is private to your account." />

{#snippet feedback(section: string)}
  {#if form?.section === section}
    <div class="mt-4">
      {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
          >{form.message}</Notice
        >{:else}<Notice tone="ok">Saved.</Notice>{/if}
    </div>
  {/if}
{/snippet}

<div class="flex max-w-3xl flex-col gap-6">
  <section class="panel p-5 sm:p-6" aria-labelledby="appearance-heading">
    <h2 id="appearance-heading" class="text-xl font-semibold text-ink">Appearance</h2>
    <p class="mt-1 mb-4 text-sm text-ink-2">Light for reading, dark for the reading room. System follows your device. Image viewers always use a dark stage.</p>
    <ThemeToggle variant="segmented" />
  </section>

  {#if data.usageCard}
    <section id="ai-usage" class="panel scroll-mt-20 p-5 sm:p-6" aria-labelledby="ai-usage-heading">
      <h2 id="ai-usage-heading" class="text-xl font-semibold text-ink">AI usage</h2>
      <EmbeddingUsage usage={data.usageCard.usage} problem={data.usageCard.problem} />
    </section>
  {/if}

  {#if data.modelUsageCard}
    <section id="model-usage" class="panel scroll-mt-20 p-5 sm:p-6" aria-labelledby="model-usage-heading">
      <h2 id="model-usage-heading" class="text-xl font-semibold text-ink">Model calls</h2>
      <ModelUsage usage={data.modelUsageCard.usage} problem={data.modelUsageCard.problem} />
    </section>
  {/if}

  <section class="panel p-5 sm:p-6" aria-labelledby="profile-heading">
    <h2 id="profile-heading" class="text-xl font-semibold text-ink">Study profile</h2>
    <form method="POST" action="?/profile" use:enhance={() => async ({ update }) => update({ reset: false })} class="mt-4 grid gap-4 sm:grid-cols-3">
      <label class="block">
        <span class="label">Exam date</span>
        <input name="exam_date" type="date" required value={data.profile?.exam_date ?? ''} class="field mt-1.5 font-mono" />
      </label>
      <label class="block">
        <span class="label">Minutes per day</span>
        <input name="daily_minutes" type="number" min="15" max="600" step="5" required value={data.profile?.daily_minutes ?? 90} class="field mt-1.5 font-mono" />
      </label>
      <fieldset class="sm:col-span-3">
        <legend class="label">Exams</legend>
        <div class="mt-1.5 flex flex-wrap gap-2">
          {#each EXAM_TARGETS as target (target.value)}
            <label
              class="cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]"
            >
              <input type="checkbox" name="exam_targets" value={target.value} checked={targets.includes(target.value)} class="sr-only" />{target.label}
            </label>
          {/each}
        </div>
      </fieldset>
      <input type="hidden" name="timezone" value={timezone} />
      <div class="sm:col-span-3"><button class="btn btn-primary" type="submit">Save profile</button></div>
    </form>
    {#if !data.profile}
      <p class="mt-3 text-xs text-muted">No study profile yet: saving here sets your exam date, the same as onboarding on Today.</p>
    {/if}
    {@render feedback('profile')}
  </section>

  <section class="panel p-5 sm:p-6" aria-labelledby="reminders-heading">
    <h2 id="reminders-heading" class="text-xl font-semibold text-ink">Reminders</h2>
    <p class="mt-1 mb-4 text-sm text-ink-2">A short nudge at the time you usually study. Notifications never contain your notes or source text.</p>
    {#if data.settingsProblem}
      <LoadIssue compact problem={data.settingsProblem} title="Reminder settings are unreachable" icon="bell" />
    {:else}
      <ReminderForm settings={data.settings} />
    {/if}
    {@render feedback('reminders')}
    <hr class="my-6 border-line" />
    <h3 class="label mb-3">Push on this device</h3>
    <PushSetup vapidKey={data.vapidKey} pushEnabled={data.pushEnabled} />
  </section>

  <section class="panel p-5 sm:p-6" aria-labelledby="install-heading">
    <h2 id="install-heading" class="text-xl font-semibold text-ink">Install the app</h2>
    <InstallApp />
  </section>

  <section class="panel p-5 sm:p-6" aria-labelledby="export-heading">
    <h2 id="export-heading" class="text-xl font-semibold text-ink">Export my data</h2>
    <DataExport exports={data.exports} problem={data.exportsProblem} />
    {@render feedback('export')}
  </section>

  <section class="panel p-5 sm:p-6" aria-labelledby="account-heading">
    <h2 id="account-heading" class="text-xl font-semibold text-ink">Account</h2>
    {#if data.user}
      <p class="mt-2 text-sm text-ink-2">{data.user.name} · {data.user.email ?? data.user.subject} · {data.user.tenantRole}</p>
    {/if}
    <div class="mt-4 flex flex-wrap gap-2">
      <form method="POST" action="/auth/logout"><button class="btn btn-ghost" type="submit">Sign out</button></form>
      {#if data.previewEnabled}
        <a class="btn btn-ghost" href="/preview" data-sveltekit-reload>Open non-release preview</a>
      {/if}
    </div>
  </section>

  <section class="panel border-danger/40 p-5 sm:p-6" aria-labelledby="danger-heading">
    <h2 id="danger-heading" class="text-xl font-semibold text-danger">Delete my account</h2>
    <DeleteAccount
      error={form?.section === 'delete' && 'error' in form ? (form.error ?? null) : null}
      queued={form?.section === 'delete' && 'deletionQueued' in form && form.deletionQueued === true}
    />
  </section>
</div>
