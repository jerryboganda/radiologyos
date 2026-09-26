<script lang="ts">
  let { authEnabled, authError }: { authEnabled: boolean; authError: string | null } = $props();
</script>

<section class="grid min-h-[70dvh] items-center gap-12 py-10 lg:grid-cols-[1.1fr_1fr]">
  <div>
    <p class="label">FCPS-II Radiology · private workspace</p>
    <h1 class="mt-4 text-4xl leading-[1.08] font-semibold text-ink sm:text-6xl">
      Read it once.<br /><span class="text-accent">Find it forever.</span>
    </h1>
    <p class="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
      Your books, notes, and cases become one searchable, cited library — with a daily plan built backwards from your
      exam date.
    </p>
    <div class="mt-8">
      {#if authEnabled}
        <a class="btn btn-primary h-12 px-6 text-base" href="/auth/login">Sign in with Keycloak <span aria-hidden="true">→</span></a>
      {:else}
        <div class="max-w-md rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
          <strong>Authentication is not configured.</strong>
          Set the OIDC variables in <code class="font-mono">apps/web/.env</code> to enable sign-in.
        </div>
      {/if}
      {#if authError}
        <p class="mt-4 text-sm text-danger" role="alert">Sign-in was not completed ({authError}). Please try again.</p>
      {/if}
    </div>
  </div>
  <div class="relative hidden aspect-square max-h-[28rem] overflow-hidden rounded-3xl border border-stage-line bg-stage lg:block" aria-hidden="true">
    <svg viewBox="0 0 400 400" class="h-full w-full">
      <defs>
        <radialGradient id="glow" cx="50%" cy="46%" r="50%">
          <stop offset="0%" stop-color="#e8e2d6" stop-opacity="0.9" />
          <stop offset="55%" stop-color="#6b665e" stop-opacity="0.35" />
          <stop offset="100%" stop-color="#050607" stop-opacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="200" cy="190" rx="130" ry="150" fill="url(#glow)" />
      <ellipse cx="200" cy="190" rx="112" ry="132" fill="none" stroke="#d9d3c7" stroke-opacity="0.35" stroke-width="6" />
      <path d="M200 70 C 170 150, 170 240, 200 310 C 230 240, 230 150, 200 70" fill="#050607" fill-opacity="0.45" />
      <rect x="226" y="150" width="74" height="54" fill="none" stroke="#f0b43c" stroke-width="2" rx="2" />
      <line x1="300" y1="177" x2="340" y2="177" stroke="#f0b43c" stroke-width="1.5" />
    </svg>
    <p class="absolute top-4 left-4 font-mono text-[0.6875rem] tracking-widest text-overlay/80">GRAINGER · P.212 · BLK 4</p>
    <p class="absolute right-4 bottom-4 font-mono text-[0.6875rem] tracking-widest text-neutral-500">W 400 L 40 · FIT</p>
  </div>
</section>
