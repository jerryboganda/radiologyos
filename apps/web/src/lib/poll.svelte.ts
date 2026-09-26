import { invalidate } from '$app/navigation';

/**
 * Re-run loads that `depends(dependency)` every few seconds while `active()`
 * is true. Backs off gently (3 s → 10 s) and pauses while the tab is hidden.
 * Must be called during component initialisation.
 */
export function pollWhile(active: () => boolean, dependency: string, base = 3000, max = 10_000): void {
  let delay = base;
  $effect(() => {
    if (!active()) {
      delay = base;
      return;
    }
    let timer = setTimeout(tick, delay);
    function tick() {
      if (document.hidden) {
        timer = setTimeout(tick, delay);
        return;
      }
      delay = Math.min(Math.round(delay * 1.3), max);
      void invalidate(dependency);
    }
    return () => clearTimeout(timer);
  });
}
