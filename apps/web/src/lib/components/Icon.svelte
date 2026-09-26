<script lang="ts">
  import { ICONS, type IconName } from './icons';

  let { name, size = 20, class: className = '' }: { name: IconName; size?: number; class?: string } =
    $props();
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.75"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  class="shrink-0 {className}"
>
  <path d={ICONS[name]} />
</svg>
