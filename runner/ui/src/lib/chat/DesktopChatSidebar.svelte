<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { listAgents, type Agent } from '../agentsApi';
  import { listInstanceThreads, type InstanceThread } from '../threadsApi';
  import { getHistory } from './chatApi';
import { onSnapshot } from '../mail/thread';
import { conversationGroups, conversationNeeds, conversationLabel, permissionTitle, senderName, visiblePlanThreads, visibleSenderThreads, type PlanMailThread } from './conversationRows';
import { chatRows, toggleChatPin } from './pins';
  import { loadNeedsYouRows } from './needsYouRows';
  import NeedsActionPin from './NeedsActionPin.svelte';

  let sessions = $state<InstanceThread[]>([]);
  let planThreads = $state<PlanMailThread[]>([]);
  let agents = $state<Agent[]>([]);
  let pins = $state<string[]>([]);
  let persistedPins: string[] = [];
  let pinRevision = 0;
  let pinSaveQueue: Promise<void> = Promise.resolve();
  let pinError = $state('');
  let editingPins = $state(false);
  let addingPins = $state(false);
  let needsCount = $state(0);
  let error = $state('');
  let loading = $state(true);
  let managerVisible = $state(false);
  let query = $state('');
  const hues = ['violet', 'blue', 'green', 'orange', 'pink'];
  let rows = $derived([
    ...(managerVisible ? [{ id: 'manager', label: 'Manager', needs: 0, sortKey: Number.MAX_SAFE_INTEGER, hue: 'violet', href: '/thread/manager', preview: 'Manager conversation' }] : []),
    ...conversationGroups(sessions, agents).map(({ thread, instances }, index) => {
      const needs = conversationNeeds(instances, agents);
      return { id: thread.agent_id, label: conversationLabel(thread), needs, sortKey: Date.parse(thread.last_activity ?? '') || 0, hue: hues[index % hues.length], href: `/thread/${encodeURIComponent(thread.agent_id)}`, preview: needs ? `${needs} permission requests` : thread.state === 'running' ? 'Active now' : thread.state === 'idle' ? 'Conversation' : thread.state };
    }),
    ...visiblePlanThreads(planThreads).map((thread) => ({ id: `plan:${thread.plan_id}`, label: thread.plan_title || thread.title || thread.plan_id || 'Plan', needs: thread.open_count, sortKey: Date.parse(thread.last_ts) || 0, hue: 'blue', href: `/threads/${encodeURIComponent(thread.thread_id)}`, preview: permissionTitle(thread.sender ?? '', thread.last_preview || thread.title) })),
    ...visibleSenderThreads(planThreads).map((thread) => {
      const senderId = thread.thread_id.slice('sender:'.length);
      const agent = agents.find((item) => item.agent_id === senderId || item.agent_id === thread.sender);
      const label = agent?.name || senderName(thread.sender || senderId);
      return { id: thread.thread_id, label, needs: thread.open_count, sortKey: Date.parse(thread.last_ts) || 0, hue: 'blue', href: `/threads/${encodeURIComponent(thread.thread_id)}`, preview: permissionTitle(thread.sender || senderId, thread.title, label) };
    }),
  ]);
  let regular = $derived(chatRows(rows, pins).filter((row) => `${row.label} ${row.preview}`.toLowerCase().includes(query.toLowerCase())));
  let pinned = $derived(rows.filter((row) => pins.includes(row.id)));
  let addable = $derived(regular);
  let activeId = $derived(page.url.pathname.startsWith('/thread/') ? decodeURIComponent(page.url.pathname.slice('/thread/'.length)) : page.url.pathname.startsWith('/threads/') ? decodeURIComponent(page.url.pathname.slice('/threads/'.length)) : '');
  async function load() {
    try {
      const [threads, people, saved, needs, mainHistory, plans] = await Promise.all([listInstanceThreads(), listAgents(), fetch('/api/pins').then((r) => r.json()), loadNeedsYouRows(), getHistory('main').catch(() => null), fetch('/api/threads').then((r) => r.ok ? r.json() as Promise<PlanMailThread[]> : []).catch(() => [])]);
      sessions = threads; agents = people;
      planThreads = plans;
      managerVisible = Boolean(mainHistory?.messages.length);
      pins = (saved.pins ?? []).map((pin: string) => sessions.find((thread) => thread.agent_id === pin || thread.role === pin)?.agent_id ?? pin);
      persistedPins = [...pins];
      needsCount = needs.length;
      loading = false;
      error = '';
    } catch { error = 'Could not load conversations.'; }
    finally { loading = false; }
  }
  onMount(() => {
    void load();
    return onSnapshot(['mailbox'], () => { void load(); });
  });
  async function changePin(id: string) {
    const next = toggleChatPin(pins, id);
    pins = next;
    const revision = ++pinRevision;
    const save = pinSaveQueue.then(async () => {
      const target = [...pins];
      const response = await fetch('/api/pins', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pins: target }) });
      if (!response.ok) throw new Error('Could not save pinned conversations.');
      persistedPins = target;
    });
    pinSaveQueue = save.catch(() => {});
    try {
      await save;
    } catch {
      if (revision === pinRevision) {
        pins = [...persistedPins];
        pinError = 'Could not save pinned conversations.';
        window.setTimeout(() => { if (revision === pinRevision) pinError = ''; }, 3000);
      }
    }
  }
</script>

<aside class="desktop-chat-sidebar" aria-label="Conversations">
  <a class="wordmark" href="/">Varde <span>Chats</span></a>
  <div class="pin-heading"><strong>Pinned</strong><button onclick={() => { editingPins = !editingPins; addingPins = false; }}>{editingPins ? 'Done' : 'Edit'}</button></div>
  <div class="pinned" class:editing={editingPins} aria-label="Pinned conversations">
    {#if loading || error || needsCount > 0}<NeedsActionPin count={needsCount} {loading} error={Boolean(error)} active={page.url.pathname === '/chat/needs'} />{/if}
    {#each pinned as row}<div class="pin-wrap"><a class="pin" href={row.href} title={row.label} aria-label={row.label}><span class={`avatar ${row.hue}`}>{row.label.slice(0, 1).toUpperCase()}</span></a>{#if editingPins}<button class="pin-toggle" aria-label={`Unpin ${row.label}`} onclick={() => changePin(row.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg></button>{/if}</div>{/each}
    {#if editingPins}<button class="pin add" aria-label="Add a pinned conversation" onclick={() => addingPins = true}><span class="avatar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></span></button>{#if addingPins}{#each addable as row}<div class="pin-wrap"><a class="pin" href={row.href} title={row.label} aria-label={`Open ${row.label}`}><span class={`avatar ${row.hue}`}>{row.label.slice(0, 1).toUpperCase()}</span></a><button class="pin-toggle" aria-label={`Pin ${row.label}`} onclick={() => changePin(row.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button></div>{/each}{/if}{/if}
  </div>
  <label class="search"><span>⌕</span><input bind:value={query} placeholder="Search conversations" aria-label="Search conversations" /></label>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if pinError}<p class="error" role="alert">{pinError}</p>{/if}
  <nav class="rows" aria-label="Chat list">{#if loading}<p class="loading-message" role="status">Loading conversations…</p>{:else if error}<p class="no-conversations">{error}</p>{:else}{#each regular as row}<a class="row" class:selected={activeId === row.id} href={row.href}><span class={`avatar ${row.hue}`}><i class:dot={row.needs > 0}></i>{row.label.slice(0, 1).toUpperCase()}</span><span class="copy"><strong>{row.label}</strong><small>{row.preview}</small></span></a>{/each}{#if !rows.length}<p class="no-conversations">{needsCount ? 'No other conversations yet.' : 'No conversations yet.'}</p>{/if}{/if}</nav>
  <nav class="bottom" aria-label="Workspace"><a href="/plans" class:active={page.url.pathname.startsWith('/plans')}>Plans</a><a href="/settings" class:active={page.url.pathname.startsWith('/settings')}>Settings</a></nav>
</aside>

<style>
  .desktop-chat-sidebar{display:none}
  @media(min-width:900px){.desktop-chat-sidebar{box-sizing:border-box;position:fixed;z-index:30;inset:0 auto 0 0;width:320px;display:flex;flex-direction:column;padding:max(20px,env(safe-area-inset-top)) 16px max(12px,env(safe-area-inset-bottom));background:var(--cf-panel);border-right:1px solid var(--cf-line);color:var(--cf-text);font:14px/1.4 system-ui,-apple-system,sans-serif}.wordmark{min-height:44px;padding:0 10px 8px;color:var(--cf-text);font-size:18px;font-weight:750;text-decoration:none}.wordmark span{color:var(--cf-muted);font-weight:500}.pin-heading{display:flex;align-items:center;justify-content:space-between;padding:0 8px;color:var(--cf-muted);font-size:12px}.pin-heading button{min-height:44px;border:0;background:transparent;color:#2670d8;font:inherit;font-weight:650}.pinned{display:grid;grid-template-columns:repeat(auto-fit,44px);gap:8px;min-height:58px;padding:4px 8px 8px}.pinned.editing{padding-bottom:12px}.pin-wrap{position:relative;width:44px;height:44px}.pin{display:grid;place-items:center;width:44px;height:44px;color:inherit;text-decoration:none}.pin.add{border:1px dashed var(--cf-muted);border-radius:50%;background:var(--cf-soft);color:var(--cf-text);cursor:pointer}.pin-toggle{position:absolute;top:-2px;right:-2px;z-index:1;width:22px;height:22px;border:2px solid var(--cf-panel);border-radius:50%;background:var(--cf-panel);color:var(--cf-muted);font-size:14px;line-height:1}.pin-toggle svg,.avatar svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.pin.add .avatar svg{width:20px;height:20px}.avatar{position:relative;display:grid;place-items:center;width:34px;height:34px;border-radius:50%;color:white;font-size:13px;font-weight:700}.violet{background:var(--cf-avatar-violet)}.blue{background:var(--cf-avatar-blue)}.green{background:var(--cf-avatar-green)}.orange{background:var(--cf-avatar-orange)}.pink{background:var(--cf-avatar-pink)}.search{display:flex;align-items:center;gap:8px;margin:4px 2px 8px;padding:0 10px;height:44px;border:1px solid var(--cf-line);border-radius:10px;color:var(--cf-muted)}.search input{width:100%;min-height:44px;border:0;outline:0;background:transparent;color:var(--cf-text);font:inherit}.rows{min-height:0;overflow:auto}.row{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:10px;color:inherit;text-decoration:none}.row.selected{background:var(--cf-soft)}.row .avatar{flex:none}.avatar i{display:none;position:absolute;right:-1px;bottom:-1px;width:10px;height:10px;border:2px solid var(--cf-panel);border-radius:50%;background:#2670d8}.avatar i.dot{display:block}.copy{min-width:0}.copy strong,.copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.copy strong{font-size:13px}.copy small{margin-top:2px;color:var(--cf-muted);font-size:12px}.bottom{display:grid;gap:4px;margin-top:auto;padding-top:12px;border-top:1px solid var(--cf-line)}.bottom a{display:flex;align-items:center;min-height:44px;padding:10px;border-radius:9px;color:var(--cf-muted);text-decoration:none}.bottom a.active{background:var(--cf-soft);color:var(--cf-text)}}
  .no-conversations,.loading-message{margin:14px 10px;color:var(--cf-muted);font-size:13px}.sidebar-skeleton,.sidebar-badge-skeleton{display:block;background:var(--cf-soft);animation:pulse 1.2s ease-in-out infinite alternate}.sidebar-skeleton{width:18px;height:18px;border-radius:50%}.sidebar-badge-skeleton{width:21px;height:21px;margin-left:auto;border-radius:99px}@keyframes pulse{to{opacity:.45}}
  .error{margin:var(--space-1) var(--space-2);color:var(--text-danger);font-size:var(--font-size-xs)}
  @media(min-width:900px){.pinned :global(.needs-action){box-sizing:border-box;grid-column:1/-1;width:auto;min-height:var(--control-h);flex-direction:row;gap:var(--space-3);padding:0 var(--space-2);border-radius:12px;color:var(--cf-text)}.pinned :global(.needs-action:hover),.pinned :global(.needs-action:focus-visible),.pinned :global(.needs-action.active){background:var(--cf-soft)}.pinned :global(.needs-action .label){max-width:none;text-align:left}.search:focus-within{outline:2px solid #2670d8;outline-offset:2px}.search input:focus-visible{outline:2px solid #2670d8;outline-offset:2px}:global(:root[data-theme=dark]) .search:focus-within,:global(:root[data-theme=dark]) .search input:focus-visible{outline-color:#91c4ff}:global(:root[data-theme=dark]) .pin-heading button{color:#71aaff}}
</style>
