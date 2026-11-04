<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import ChatThread from '../../../lib/chat/ChatThread.svelte';
  import ChatHeader from '../../../lib/ChatHeader.svelte';
  import { getInstanceThread, listInstanceThreads, type InstanceThread } from '../../../lib/threadsApi';
  import { listAgents } from '../../../lib/agentsApi';
  import { conversationLabel } from '../../../lib/chat/conversationRows';
  import { Card } from '../../../lib/ui';
  import Skeleton from '../../../lib/ui/Skeleton.svelte';
  import { cacheRead, cacheWrite } from '../../../lib/cache';

  let thread = $state<InstanceThread | null>(null);
  let error = $state('');
  let loading = $state(true);
  let roleEnabled = $state<boolean | null>(null);
  let instanceActivity = $state<{ label: string; state: string; last_activity: string | null; pending_count: number }[]>([]);
  const agentId = $derived(page.params.agentId ?? '');
  const isManager = $derived(agentId === 'manager');
  const cacheKey = () => `varde:cache:instance-thread:${encodeURIComponent(agentId)}:v1`;
  async function load() {
    if (!agentId) {
      error = 'Thread not found.';
      loading = false;
      return;
    }
    try {
      const loaded = await getInstanceThread(agentId);
      thread = loaded;
      const [threads, agents] = await Promise.all([listInstanceThreads(), listAgents()]);
      const pendingAgents = new Set(agents.filter((agent) => agent.pending_requests.length > 0).map((agent) => agent.agent_id));
      const group = threads.filter((item) => item.role === loaded.role && (!['archived', 'completed', 'error', 'failed', 'stopped', 'terminated', 'cancelled'].includes(item.state.toLowerCase()) || pendingAgents.has(item.agent_id)))
        .sort((a, b) => Number(pendingAgents.has(b.agent_id)) - Number(pendingAgents.has(a.agent_id)) || (b.last_activity ?? '').localeCompare(a.last_activity ?? ''));
      instanceActivity = group.map((item, index) => ({
        label: group.length > 1 ? `${conversationLabel(item)} instance ${index + 1}` : conversationLabel(item), state: item.state, last_activity: item.last_activity,
        pending_count: agents.find((agent) => agent.agent_id === item.agent_id)?.pending_requests.length ?? 0,
      }));
      cacheWrite(cacheKey(), { thread, instanceActivity });
      error = '';
    }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load this thread.'; }
    finally { loading = false; }
  }

  onMount(() => {
    let active = true;
    if (isManager) {
      fetch('/api/roles', { cache: 'no-store' })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => { if (active && payload) roleEnabled = payload.roles?.['manager-bot']?.enabled === true; })
        .catch(() => {});
    } else {
      const cached = cacheRead<{ thread: InstanceThread; instanceActivity: typeof instanceActivity }>(cacheKey(), 10 * 60 * 1000);
      if (cached) { thread = cached.thread; instanceActivity = cached.instanceActivity; loading = false; }
      void load();
    }
    return () => {
      active = false;
    };
  });
</script>

<svelte:head><title>{isManager ? 'Manager' : thread?.label ?? 'Instance thread'} · Varde Runner</title></svelte:head>
<div class="page">
  <ChatHeader title={isManager ? 'Manager' : thread?.label ?? 'Conversation'} subtitle={isManager ? (roleEnabled === null ? '\u00a0' : roleEnabled ? 'Manager bot' : 'Off') : thread?.state ?? 'Loading conversation'} />
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if isManager}
    <ChatThread threadKey="main" {roleEnabled} composerLabel="Message Manager…" hideHeader>
    </ChatThread>
  {:else if loading}<div aria-busy="true"><Skeleton rows={5} card /></div>
  {:else if thread}
    <ChatThread threadKey={`instance:${agentId}`} {instanceActivity} composerLabel={`Message ${conversationLabel(thread)}`} hideHeader />
  {:else}<Card><p>Instance thread not found.</p></Card>{/if}
</div>
<style>
  .page{display:flex;flex:1;flex-direction:column;gap:0;min-width:0;min-height:0;overflow:hidden}.page :global(.chat-thread){flex:1;height:auto;min-height:0}.error{margin:0;padding:var(--space-3);border-radius:var(--radius-control);background:var(--status-blocked-bg);color:var(--text-muted);overflow-wrap:anywhere}
</style>
