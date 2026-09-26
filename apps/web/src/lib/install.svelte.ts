// Captures the browser's install prompt early (it fires once, often before the
// Settings page mounts) so Settings can offer "Install radbrain" later.

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export const installState = $state<{ prompt: InstallPromptEvent | null; installed: boolean }>({
  prompt: null,
  installed: false
});

/** Call once from the root layout's onMount; returns the cleanup. */
export function watchInstallPrompt(): () => void {
  installState.installed = matchMedia('(display-mode: standalone)').matches;
  const onPrompt = (event: Event) => {
    event.preventDefault();
    installState.prompt = event as InstallPromptEvent;
  };
  const onInstalled = () => {
    installState.installed = true;
    installState.prompt = null;
  };
  window.addEventListener('beforeinstallprompt', onPrompt);
  window.addEventListener('appinstalled', onInstalled);
  return () => {
    window.removeEventListener('beforeinstallprompt', onPrompt);
    window.removeEventListener('appinstalled', onInstalled);
  };
}

/** Show the native prompt; true when the user accepted. */
export async function promptInstall(): Promise<boolean> {
  const event = installState.prompt;
  if (!event) return false;
  installState.prompt = null;
  await event.prompt();
  const { outcome } = await event.userChoice;
  if (outcome === 'accepted') installState.installed = true;
  return outcome === 'accepted';
}
