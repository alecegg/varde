<script lang="ts">
  import '../style.css';
  import '../lib/chat/chatTokens.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { Button, Input } from '../lib/ui';
  import ChatShell from '../lib/chat/ChatShell.svelte';
  import { csrfFetch, loadPairing, submitPairing, type PairingState } from '../lib/pairing';
  import { applyTheme, savedThemeMode, type ThemeMode } from '../lib/theme';
  import { refreshIconLinks, type AppIcon } from '../lib/appIcon';
  import { refreshWhenVisible } from '../lib/refresh';
  import { initialConnection, nextConnection, setConnectionStatus, type ConnectionEvent } from '../lib/connection';
  let { children } = $props();
  let needsYouCount = $state(0);
  let themeMode = $state<ThemeMode>('system');
  let connection = $state(initialConnection(Date.now()));
  let now = $state(Date.now());
  let connectionNoticeDismissed = $state(false);
  let connectionAnnouncement = $state('');
  let wasConnectionStale = false;
  let chatUnread = $state(false);
  let pairing = $state<PairingState>({ enforced: false, paired: true, csrf: null });
  let pairCode = $state('');
  let pairError = $state('');
  async function pair(event: SubmitEvent) {
    event.preventDefault();
    pairError = '';
    try { await submitPairing(window.fetch, pairCode); location.reload(); } catch (error) { pairError = error instanceof Error ? error.message : 'Pairing failed'; }
  }
  async function loadNeedsYouCount() {
    try { const count = await (await fetch('/api/needs-you-count')).json(); needsYouCount = count.needs_you_count ?? 0; } catch { /* Keep the last count. */ }
  }
  async function refreshChatUnread() {
    if (page.url.pathname === '/chat' || page.url.pathname === '/thread/manager') return;
    try {
      const response = await fetch('/api/chat?thread=main&limit=1');
      if (!response.ok) return;
      const history = await response.json();
      let seen = 0;
      try { seen = Number(localStorage.getItem('varde:chat:main:seen') ?? 0); } catch { /* Best effort. */ }
      chatUnread = Number(history.latest_seq ?? 0) > seen;
    } catch { /* Keep the last unread state. */ }
  }
  onMount(() => {
    const plainFetch = window.fetch.bind(window);
    window.fetch = csrfFetch(plainFetch, () => pairing.csrf, location.origin);
    loadPairing(plainFetch).then((state) => { pairing = state; }).catch(() => {});
    themeMode = savedThemeMode();
    applyTheme(themeMode);
    const themeChanged = (event: Event) => { themeMode = (event as CustomEvent<ThemeMode>).detail; };
    window.addEventListener('runner:theme', themeChanged);
    const iconChanged = (event: Event) => refreshIconLinks((event as CustomEvent<AppIcon>).detail);
    window.addEventListener('runner:app-icon', iconChanged);
    fetch('/api/settings').then((response) => response.json()).then((settings) => {
      if (settings.app_icon === 'dark' || settings.app_icon === 'slate-bronze') {
        iconChanged(new CustomEvent('runner:app-icon', { detail: settings.app_icon }));
      }
    }).catch(() => {});
    const preference = matchMedia('(prefers-color-scheme: dark)');
    const updateSystemTheme = () => { if (themeMode === 'system') applyTheme('system'); };
    preference.addEventListener('change', updateSystemTheme);
    let events = new EventSource('/events');
    const step = (event: ConnectionEvent) => {
      now = Date.now();
      const previous = connection.status;
      connection = nextConnection(connection, event, now);
      setConnectionStatus(connection.status);
      if (connection.status === 'healthy') {
        connectionNoticeDismissed = false;
        if (wasConnectionStale) {
          connectionAnnouncement = 'Reconnected';
          requestAnimationFrame(() => {
            const main = document.querySelector<HTMLElement>('.shell-content');
            main?.setAttribute('tabindex', '-1');
            main?.focus();
          });
        }
        wasConnectionStale = false;
      } else if (connection.status === 'stale') wasConnectionStale = true;
      if (connection.status !== previous) window.dispatchEvent(new CustomEvent('runner:connection', { detail: connection.status }));
    };
    loadNeedsYouCount();
    refreshChatUnread();
    const chatRead = () => { chatUnread = false; };
    window.addEventListener('runner:chat-read', chatRead);
    const stopVisibleRefresh = refreshWhenVisible(loadNeedsYouCount);
    const timer = setInterval(() => step('tick'), 1000);
    const chatTimer = setInterval(refreshChatUnread, 15_000);
    const bindEvents = () => {
      events.addEventListener('update', (event) => {
        try {
          const update = JSON.parse((event as MessageEvent).data);
          if (typeof update?.needs_you_count === 'number') needsYouCount = update.needs_you_count; else loadNeedsYouCount();
          if (Array.isArray(update?.topics)) window.dispatchEvent(new CustomEvent('runner:snapshot', { detail: { topics: update.topics } }));
        } catch { /* Ignore malformed snapshots. */ }
      });
      events.onopen = () => step('open');
      events.onerror = () => step('error');
    };
    bindEvents();
    const retryConnection = () => {
      events.close();
      connection = initialConnection(Date.now());
      setConnectionStatus(connection.status);
      window.dispatchEvent(new CustomEvent('runner:connection', { detail: connection.status }));
      events = new EventSource('/events');
      bindEvents();
    };
    window.addEventListener('runner:connection-retry', retryConnection);
    return () => { window.removeEventListener('runner:theme', themeChanged); window.removeEventListener('runner:app-icon', iconChanged); window.removeEventListener('runner:chat-read', chatRead); window.removeEventListener('runner:connection-retry', retryConnection); preference.removeEventListener('change', updateSystemTheme); events.close(); clearInterval(timer); clearInterval(chatTimer); stopVisibleRefresh(); };
  });
</script>
{#if pairing.enforced && !pairing.paired}
  <form class="pairing" onsubmit={pair}>
    <h1>Pair this browser</h1>
    <p>Enter the code printed by <code>varde-runner serve</code>. Writes stay locked until you do.</p>
    <Input label="Pairing code" bind:value={pairCode} autocomplete="off" autocapitalize="characters" spellcheck={false} error={pairError || undefined} />
    <Button type="submit" disabled={!pairCode.trim()}>Pair</Button>
  </form>
{/if}
<ChatShell {chatUnread}>
  {#snippet children()}
    {@render children()}
  {/snippet}
</ChatShell>
{#if connection.status === 'stale' && !connectionNoticeDismissed}
  <div class="connection-notice" role="alert">
    <span>Connection lost. Your draft and failed messages are saved on this device.</span>
    <Button variant="secondary" onclick={() => window.dispatchEvent(new Event('runner:connection-retry'))}>Retry</Button>
    <Button variant="secondary" onclick={() => { connectionNoticeDismissed = true; requestAnimationFrame(() => document.querySelector<HTMLElement>('.shell-content')?.focus()); }}>Dismiss</Button>
  </div>
{/if}
<p class="visually-hidden" role="status">{connectionAnnouncement}</p>

<style>
  .pairing{position:relative;z-index:10;display:grid;gap:var(--space-3);box-sizing:border-box;max-width:min(420px,100%);margin:calc(var(--topbar-height-desktop-safe) + var(--space-4)) auto 0;padding:var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-control);background:var(--surface-1)}.pairing h1{margin:0;font-size:var(--font-size-lg)}.pairing p{margin:0;color:var(--text-muted)}
  .pairing{margin-top:var(--space-4)}
  .connection-notice{position:fixed;right:max(var(--space-4),env(safe-area-inset-right));bottom:max(var(--space-4),env(safe-area-inset-bottom));z-index:40;display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);max-width:min(42rem,calc(100vw - 2 * var(--space-4)));padding:var(--space-3);border:var(--line) solid var(--status-waiting-fg);border-radius:var(--radius-card);background:var(--surface-1);color:var(--text-body);box-shadow:var(--elevation-card)}
</style>
