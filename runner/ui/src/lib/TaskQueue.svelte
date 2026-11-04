<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from './queue';
  import { taskChip } from './plans';
  import { refreshWhenVisible } from './refresh';
  import { Badge, Card } from './ui';

  type Item = { task_id: string; status: string; blocked: boolean; blocked_by: { task_id: string }[]; worktree: string; fix: boolean };
  type RoleSession = { role: string; session_id: string; worktree: string; context_tokens: number | null };
  type Queue = { items: Item[]; role_sessions: RoleSession[] };
  let queue = $state<Queue | null>(null);
  let error = $state('');
  const planId = $derived(page?.params?.id ?? '');

  async function load() {
    if (!planId) return;
    try { queue = await api<Queue>(`/api/plans/${encodeURIComponent(planId)}/task-queue`); error = ''; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load task queue'; }
  }

  onMount(() => {
    let active = true;
    void load();
    const stopRefresh = refreshWhenVisible(() => { if (active) void load(); });
    return () => { active = false; stopRefresh(); };
  });
</script>

<Card title="Task queue">
  {#if error}<p role="alert">{error}</p>
  {:else if queue}
    {#each queue.items as item (item.task_id)}
      <article class="item">
        <strong>{item.task_id}{#if item.fix} · fix{/if}</strong>
        <Badge tone={item.blocked ? 'blocked' : taskChip(item.status).tone}>{item.blocked ? `Blocked${item.blocked_by.length ? ` by ${item.blocked_by.map((row) => row.task_id).join(', ')}` : ''}` : taskChip(item.status).label}</Badge>
        <code>{item.worktree}</code>
      </article>
    {:else}<p class="muted">No task queue is configured for this plan.</p>{/each}
    {#if queue.role_sessions.length}
      <h3>Role session context</h3>
      {#each queue.role_sessions as session (`${session.session_id}:${session.role}`)}
        <p class="session">{session.role} · {session.context_tokens === null ? 'No usage recorded' : `${session.context_tokens.toLocaleString()} tokens`} · {session.worktree}</p>
      {/each}
    {/if}
  {:else}<p class="muted">Loading task queue…</p>{/if}
</Card>

<style>
  .item{display:grid;grid-template-columns:minmax(8rem,1fr) auto;gap:var(--space-2);align-items:center;padding-block:var(--space-2);border-top:var(--line) solid var(--border-subtle)}
  code{grid-column:1/-1;overflow-wrap:anywhere;color:var(--text-muted);font-size:var(--font-size-xs)}
  h3{margin:var(--space-3) 0 var(--space-1);font-size:var(--font-size-sm)}
  .session,.muted{margin:0;padding-block:var(--space-1);color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
</style>
