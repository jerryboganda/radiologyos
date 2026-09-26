<script lang="ts">
  let { user }: { user: { subject: string; name: string; email?: string; tenantRole: string } } = $props();
  let initials = $derived(
    user.name
      .split(/\s+/)
      .map((part) => part[0] ?? '')
      .join('')
      .slice(0, 2)
      .toUpperCase()
  );
</script>

<div class="account-card rounded-xl border border-line bg-surface p-3" data-user-subject={user.subject}>
  <div class="flex items-center gap-3">
    <span
      class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono text-xs font-semibold text-accent"
      aria-hidden="true">{initials}</span
    >
    <div class="min-w-0">
      <p class="truncate text-sm font-semibold text-ink">{user.name}</p>
      <p class="truncate text-xs text-muted">{user.email ?? user.subject} · {user.tenantRole}</p>
    </div>
  </div>
  <form method="POST" action="/auth/logout" class="mt-3">
    <button class="btn btn-ghost w-full min-h-9 py-1.5 text-xs" type="submit">Sign out</button>
  </form>
</div>
