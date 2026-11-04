<script lang="ts">
  import { onMount } from 'svelte';
  import { getHome } from '../homeApi';
  import { listAgents, type Agent } from '../agentsApi';
  import { listInstanceThreads, type InstanceThread } from '../threadsApi';
  import { getHistory } from './chatApi';
  import { onSnapshot } from '../mail/thread';
  import NeedsYou from '../NeedsYou.svelte';
  import NeedsActionPin from './NeedsActionPin.svelte';
  import { conversationGroups, conversationNeeds, conversationLabel, permissionTitle, senderName, visiblePlanThreads, visibleSenderThreads, planPreview, type PlanMailThread } from './conversationRows';
  import { chatRows, toggleChatPin } from './pins';
  import { loadNeedsYouRows } from './needsYouRows';
  import { cacheRead, cacheWrite } from '../cache';
  import Skeleton from '../ui/Skeleton.svelte';
  import { loadingView } from '../loadingState';

  let { needsOnly = false, hideHeader = false }: { needsOnly?: boolean; hideHeader?: boolean } = $props();

  let sessions = $state<InstanceThread[]>([]);
  let planThreads = $state<PlanMailThread[]>([]);
  let agents = $state<Agent[]>([]);
  let summaries = $state<Awaited<ReturnType<typeof getHome>>['roles']>([]);
  let pins = $state<string[]>([]);
  let persistedPins: string[] = [];
  let pinRevision = 0;
  let pinSaveQueue: Promise<void> = Promise.resolve();
  let pinError = $state('');
  let edit = $state(false);
  let addPins = $state(false);
  let error = $state('');
  let loading = $state(true);
  let needsCount = $state(0);
  let firstNeed = $state('');
  let managerVisible = $state(false);
  let managerLastActivity = $state<string | null>(null);
  const hues = ['violet', 'blue', 'green', 'orange', 'pink'];
  let rows = $derived([
    ...(managerVisible ? [{ id: 'manager', label: 'Manager', initials: 'MG', hue: 'violet', needs: 0, sortKey: Date.parse(managerLastActivity ?? '') || Number.MAX_SAFE_INTEGER, preview: summaries.find((item) => item.agent_id === 'manager')?.current?.title || 'Manager conversation', time: formatTime(managerLastActivity), href: '/thread/manager' }] : []),
    ...conversationGroups(sessions, agents).map(({ thread, instances }, index) => {
      const agentNeeds = conversationNeeds(instances, agents);
      const summary = summaries.find((item) => item.agent_id === thread.agent_id || item.role === thread.role);
      const label = conversationLabel(thread);
      const needs = Math.max(agentNeeds, summary?.needs_you ?? 0);
      const currentTitle = summary?.current?.title ?? '';
      const preview = needs ? statusPreview(summary?.state, currentTitle) : currentTitle || (thread.state === 'running' ? 'Active now' : thread.state === 'idle' ? 'Conversation' : titleCase(thread.state));
      const summaryIndex = summaries.findIndex((item) => item.agent_id === thread.agent_id || item.role === thread.role);
      return { id: thread.agent_id, label, initials: initials(label), hue: hues[(summaryIndex >= 0 ? summaryIndex : index) % hues.length], needs, sortKey: Date.parse(thread.last_activity ?? '') || 0, preview, time: formatTime(thread.last_activity), href: `/thread/${encodeURIComponent(thread.agent_id)}` };
    }),
    ...visiblePlanThreads(planThreads).map((thread) => ({ id: `plan:${thread.plan_id}`, label: thread.plan_title || thread.title || thread.plan_id || 'Plan', initials: initials(thread.plan_title || thread.title || 'Plan'), hue: 'blue', needs: thread.open_count, sortKey: Date.parse(thread.last_ts) || 0, preview: planPreview(thread), time: formatTime(thread.last_ts), href: `/threads/${encodeURIComponent(thread.thread_id)}` })),
    ...visibleSenderThreads(planThreads).map((thread) => {
      const senderId = thread.thread_id.slice('sender:'.length);
      const agent = agents.find((item) => item.agent_id === senderId || item.agent_id === thread.sender);
      const label = agent?.name || senderName(thread.sender || senderId);
      const summary = permissionTitle(thread.sender || senderId, thread.title, label);
      return { id: thread.thread_id, label, initials: initials(label), hue: 'blue', needs: thread.open_count, sortKey: Date.parse(thread.last_ts) || 0, preview: summary || permissionTitle(thread.sender || senderId, thread.last_preview, label), time: formatTime(thread.last_ts), href: `/threads/${encodeURIComponent(thread.thread_id)}` };
    }),
  ]);
  let visibleRows = $derived(chatRows(rows, pins));
  let listView = $derived(loadingView(loading, rows.length > 0));
  let displayedRows = $derived(visibleRows);
  let pinnedRows = $derived(pins.flatMap((id) => {
    const row = rows.find((item) => item.id === id);
    return row ? [row] : [];
  }));
  let addableRows = $derived(rows.filter((row) => !pins.includes(row.id)));
  const CACHE_KEY = 'varde:cache:chat-list:v1';
  const CACHE_MAX_AGE_MS = 10 * 60 * 1000;

  function titleCase(value: string) { return value.replace(/(^|[-\s])\w/g, (part) => part.toUpperCase()); }
  function statusPreview(state: string | undefined, title: string): string {
    if (state === 'failed' || /failed|retry/i.test(title)) return 'Run failed';
    if (/question|which|choose|\?/.test(title.toLowerCase())) return 'Question for you';
    return 'Needs your approval';
  }
  function formatTime(value: string | null): string {
    if (!value || !Number.isFinite(Date.parse(value))) return '';
    const date = new Date(value);
    const now = new Date();
    if (date.toDateString() !== now.toDateString()) return 'Yesterday';
    return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(date).replace(/\s?(?:AM|PM)$/i, '');
  }
  function initials(label: string) {
    const words = label.split(/[-\s]+/);
    return words.length > 1 ? words.slice(0, 2).map((word) => word[0]?.toUpperCase() ?? '').join('') : label.slice(0, 2).toUpperCase();
  }
  async function load() {
    if (!rows.length) loading = true;
    try {
      const [threads, people, saved, needs, mainHistory, home, plans] = await Promise.all([
        listInstanceThreads(), listAgents(), fetch('/api/pins', { cache: 'no-store' }).then((response) => response.ok ? response.json() : { pins: [] }),
        loadNeedsYouRows().catch(() => []),
        getHistory('main').catch(() => null), getHome().catch(() => ({ roles: [] })),
        fetch('/api/threads', { cache: 'no-store' }).then((response) => response.ok ? response.json() as Promise<PlanMailThread[]> : []).catch(() => []),
      ]);
      managerVisible = Boolean(mainHistory?.messages.length);
      managerLastActivity = mainHistory?.messages.at(-1)?.created_at ?? null;
      sessions = threads;
      planThreads = plans;
      agents = people;
      summaries = home.roles;
      const savedPins: string[] = Array.isArray(saved.pins) ? saved.pins : [];
      pins = savedPins.map((pin) => sessions.find((thread) => thread.agent_id === pin || thread.role === pin)?.agent_id ?? pin);
      persistedPins = [...pins];
      needsCount = needs.length;
      const first = needs[0];
      firstNeed = first?.kind === 'permission'
        ? first.value.request.request_id
        : first?.kind === 'thread' ? String(first.decision.msg_id ?? '') : '';
      error = '';
      cacheWrite(CACHE_KEY, { sessions, planThreads, agents, summaries, pins, needsCount, firstNeed, managerVisible, managerLastActivity });
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load conversations.'; }
    finally { loading = false; }
  }
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
  onMount(() => {
    const cached = cacheRead<{ sessions: InstanceThread[]; planThreads: PlanMailThread[]; agents: Agent[]; summaries: typeof summaries; pins: string[]; needsCount: number; firstNeed: string; managerVisible: boolean; managerLastActivity: string | null }>(CACHE_KEY, CACHE_MAX_AGE_MS);
    if (cached && Array.isArray(cached.sessions) && Array.isArray(cached.planThreads) && Array.isArray(cached.agents) && Array.isArray(cached.summaries) && Array.isArray(cached.pins)) {
      sessions = cached.sessions; planThreads = cached.planThreads; agents = cached.agents; summaries = cached.summaries;
      pins = cached.pins; persistedPins = [...cached.pins]; needsCount = cached.needsCount; firstNeed = cached.firstNeed;
      managerVisible = cached.managerVisible; managerLastActivity = cached.managerLastActivity;
      loading = !(cached.sessions.length || cached.planThreads.length || cached.managerVisible);
    }
    void load();
    return onSnapshot(['mailbox'], () => { void load(); });
  });
</script>

<svelte:head><title>Varde Runner · Chats</title></svelte:head>
<div class="chat-list">
{#if needsOnly}<NeedsYou chat />{/if}
  {#if !needsOnly}<section class="pin-section" aria-label="Pinned conversations">
    <div class="pin-heading"><span>Pinned</span><button onclick={() => { edit = !edit; addPins = false; }}>{edit ? 'Done' : 'Edit'}</button></div>
    <nav class="bubbles" class:editing={edit} class:has-overflow={pinnedRows.length + 1 > 4} aria-label="Pinned chats">
      {#if loading || error || needsCount > 0}<NeedsActionPin count={needsCount} {loading} error={Boolean(error)} href={firstNeed ? `/chat/needs?item=${encodeURIComponent(firstNeed)}` : '/chat/needs'} />{/if}
      {#each pins.map((id) => pinnedRows.find((row) => row.id === id)).filter((row) => row !== undefined) as row}
        <div class="bubble-wrap"><a class="bubble" href={row.href}><span class={`avatar ${row.hue}`}>{row.initials}</span><span class="label">{row.label}</span></a>
          {#if edit}<button class="pin-toggle" aria-label={`Unpin ${row.label}`} onclick={() => changePin(row.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg></button>{/if}
        </div>
      {/each}
      {#if edit && addPins}
        {#each addableRows as row}<div class="bubble-wrap"><a class="bubble" href={row.href}><span class={`avatar ${row.hue}`}>{row.initials}</span><span class="label">{row.label}</span></a><button class="pin-toggle" aria-label={`Pin ${row.label}`} onclick={() => changePin(row.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button></div>{/each}
      {:else if edit}<button class="bubble add" onclick={() => addPins = true}><span class="avatar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></span><span class="label">Add</span></button>{/if}
    </nav>
  </section>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if pinError}<p class="error" role="alert">{pinError}</p>{/if}
  {#if listView === 'skeleton'}<div aria-busy="true"><Skeleton rows={5} /></div>
  {:else if !needsOnly && !rows.length && !error}<section class="empty"><strong>{needsCount ? 'No other conversations yet' : 'No conversations yet'}</strong><span>{needsCount ? 'A pending item still needs your attention above.' : 'Start a chat to see it here.'}</span><a href="/new-item">Start a chat</a></section>
  {:else if !needsOnly}<main><h2>Recent</h2>{#each displayedRows as row}
    <a class="chat-row" href={row.href}><span class={`small-avatar ${row.hue}`} class:attention={row.needs > 0}>{row.initials}</span><span class="copy"><strong>{row.label}</strong><span>{row.preview}</span></span><span class="time">{row.time ?? ''}</span></a>
  {/each}</main>{/if}
</div>

<style>
  .brand{width:44px;height:44px;min-width:44px;min-height:44px;padding:0;background:transparent}.brand span{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:#1d2635}
  :global(.chat-shell.landing){font-size:16px}.top{height:62px;display:flex;align-items:center;gap:10px;padding:0 18px;background:var(--cf-bg)}.brand,.avatar,.small-avatar{display:grid;place-items:center;flex:none;border:0;border-radius:50%;font-weight:700;color:#fff}.brand{width:44px;height:44px;padding:0;background:transparent;font-size:14px;cursor:pointer}.brand span{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:#1d2635}.top h1{flex:1;margin:0;font-size:23px;letter-spacing:-.02em}.icon{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:50%;background:var(--cf-panel);box-shadow:0 1px 5px #0002;color:var(--cf-text);font-size:20px;text-decoration:none}.icon svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.pin-section{padding-top:9px}.pin-heading{display:flex;align-items:center;justify-content:space-between;padding:5px 18px;color:var(--cf-muted)}.pin-heading{font-size:15px}.pin-heading button{border:0;background:transparent;color:#2670d8;font-size:15px;font-weight:650}.pin-actions{font-size:12px}.bubbles{display:grid;grid-template-columns:repeat(auto-fit,minmax(64px,76px));gap:12px;overflow:visible;padding:12px 18px 14px}.bubble,.bubble-wrap{position:relative;display:flex;width:76px;flex-direction:column;align-items:center;gap:7px;color:var(--cf-muted);text-decoration:none;font-size:12px}.bubble{border:0;padding:0;background:transparent;font-family:inherit;cursor:pointer}.avatar{width:62px;height:62px;font-size:16px;box-shadow:0 0 0 1px var(--cf-line)}.badge{position:absolute;top:0;right:4px;min-width:21px;height:21px;padding:0 5px;border:2px solid var(--cf-bg);border-radius:99px;background:#2670d8;color:#fff;font-size:11px;font-weight:800;display:grid;place-items:center}.label{max-width:76px;min-height:28px;overflow:hidden;text-overflow:ellipsis;text-align:center;line-height:1.15}.violet{background:var(--cf-avatar-violet)}.blue{background:var(--cf-avatar-blue)}.green{background:var(--cf-avatar-green)}.orange{background:var(--cf-avatar-orange)}.pink{background:var(--cf-avatar-pink)}.pin-toggle{position:absolute;top:-2px;left:3px;z-index:1;width:26px;height:26px;border:2px solid var(--cf-bg);border-radius:50%;background:var(--cf-panel);color:var(--cf-muted);font-size:16px}.add .avatar{background:var(--cf-soft);color:var(--cf-text);border:1px dashed var(--cf-muted);box-shadow:none}.bubbles.editing{grid-template-columns:repeat(auto-fit,minmax(56px,64px));gap:6px;padding-right:12px;padding-left:12px}.bubbles.editing .bubble,.bubbles.editing .bubble-wrap{width:64px}.bubbles.editing .avatar{width:56px;height:56px}.bubbles.editing .label{max-width:64px}main{padding:4px 0 32px}main h2{margin:8px 18px 4px;color:var(--cf-muted);font-size:13px;font-weight:650;letter-spacing:.02em}.chat-row{display:flex;align-items:center;gap:13px;min-height:78px;padding:13px 18px;color:inherit;text-decoration:none}.small-avatar{position:relative;width:48px;height:48px;font-size:14px}.small-avatar.attention:after{position:absolute;right:-1px;bottom:-1px;width:13px;height:13px;border:2px solid var(--cf-bg);border-radius:50%;background:#2670d8;content:''}.copy{flex:1;min-width:0}.copy strong,.copy span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.copy strong{font-size:16px;font-weight:680}.copy span,.time{margin-top:3px;color:var(--cf-muted);font-size:14px}.time{align-self:flex-start;white-space:nowrap}.empty{min-height:300px;display:grid;place-content:center;text-align:center;color:var(--cf-muted)}.empty strong{color:var(--cf-text);font-size:19px}.empty a{justify-self:center;margin-top:16px;padding:12px 18px;border-radius:99px;background:var(--cf-primary);color:var(--cf-primary-ink);text-decoration:none}.empty a:focus-visible{outline:2px solid var(--cf-text);outline-offset:2px}.error{padding:0 18px;color:var(--cf-bad)}.filtered-head{display:flex;align-items:center;gap:12px;padding:8px 18px 16px}.back{width:40px;height:40px;border:0;border-radius:50%;background:var(--cf-soft);font-size:22px}@media(min-width:761px){.top,.pin-section,main,.filtered-head{max-width:520px;margin-right:auto;margin-left:auto}}
  .chat-list{--cf-bg:#fbfbfd;--cf-panel:#fff;--cf-soft:#f1f1f5;--cf-line:#eeeef2;--cf-text:#17181c;--cf-muted:#626775;color:var(--cf-text)}
  :global([data-theme="dark"]) .chat-list{--cf-bg:#0d0e11;--cf-panel:#16171c;--cf-soft:#1d1f26;--cf-line:#292b32;--cf-text:#f3f3f6;--cf-muted:#a3a8b6}
  .brand{width:38px;height:38px;background:#1d2635}.brand span{width:auto;height:auto;background:none}
  .top h1{font-size:19px}
  .pin-section{padding-top:0}
  .pin-heading{padding:5px 18px;font-size:13px}
  .pin-heading button{min-height:44px;padding:0 4px;font-size:14px}
  .bubbles{padding-top:13px}
  .label{min-height:28px;white-space:nowrap}
  main h2{margin:0;padding:8px 18px 4px}
  .copy span{margin-top:3px;font-size:14px}
  .time{margin-top:0;padding-top:4px;font-size:12px}
  .avatar svg,.pin-toggle svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.add .avatar svg{width:20px;height:20px}
  .brand:focus-visible{outline:2px solid #2670d8;outline-offset:2px}
  :global(:root[data-theme=dark]) .pin-heading button{color:#71aaff}
  .brand{width:44px;height:44px;min-width:44px;min-height:44px;background:transparent}
  .brand span{width:38px;height:38px;background:#1d2635}
  .icon{width:44px;height:44px}
  .pin-heading button{min-height:44px}
  .pin-heading button{min-width:44px}
  .top,.pin-heading,main h2,.filtered-head{padding-inline:16px}
  .chat-row{padding-inline:16px}
  .bubbles{padding-inline:16px}
  .bubbles.editing{padding-inline:16px}
  .pin-toggle{top:-8px;left:-8px;width:44px;height:44px}
</style>
