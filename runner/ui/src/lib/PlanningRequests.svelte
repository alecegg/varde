<script lang="ts">
  import { onMount } from 'svelte';
  import { onSnapshot } from './mail/thread';
  import { getConnectionStatus } from './connection';
  import { Button, Badge, Card, Cluster } from './ui';
  type Item = Record<string, any>;
  let items: Item[] = $state([]), mailbox: Item[] = $state([]), workspaces: { id: string; last_used: boolean }[] = $state([]), project = $state(''), status = $state(''), busy = $state(false);

  function applyMailbox(mail: Record<string, any>) {
    mailbox = [...(mail.open ?? []), ...(mail.permissions ?? [])].filter((item) => item.kind !== 'permission' && !item.msg_id?.startsWith('perm:') && !item.sender?.startsWith('workitem-'));
  }
  async function loadWorkItems() {
    const response = await fetch('/api/work-items');
    if (!response.ok) throw new Error('Could not load work items');
    items = (await response.json()).work_items ?? [];
  }
  async function loadMailbox() {
    const response = await fetch('/api/mailbox');
    if (!response.ok) throw new Error('Could not load mailbox');
    applyMailbox(await response.json());
  }
  async function load() {
    await Promise.all([loadWorkItems(), loadMailbox()]);
  }
  async function loadWorkspaces() {
    const response = await fetch('/api/workspaces');
    if (!response.ok) throw new Error('Could not load repositories');
    workspaces = (await response.json()).workspaces ?? [];
    project = (workspaces.find((workspace) => workspace.last_used) ?? workspaces[0])?.id ?? '';
  }
  onMount(() => {
    let fallback: ReturnType<typeof setInterval> | undefined;
    loadWorkspaces().catch((error) => status = error.message);
    load().catch((error) => status = error.message);
    const stopSnapshot = onSnapshot(['work_items', 'mailbox'], (eventTopics) => {
      const updates = [];
      if (eventTopics.includes('work_items')) updates.push(loadWorkItems());
      if (eventTopics.includes('mailbox')) updates.push(loadMailbox());
      Promise.all(updates).catch(() => {});
    });
    const connection = (event: Event) => {
      if ((event as CustomEvent<string>).detail === 'healthy') { if (fallback) clearInterval(fallback); fallback = undefined; }
      else fallback ??= setInterval(() => load().catch(() => {}), 3000);
    };
    if (getConnectionStatus() !== 'healthy') fallback ??= setInterval(() => load().catch(() => {}), 3000);
    window.addEventListener('runner:connection', connection);
    return () => { stopSnapshot(); window.removeEventListener('runner:connection', connection); if (fallback) clearInterval(fallback); };
  });
  async function submit(source: Item) {
    const requestText = [source.asked, source.why, source.body].filter(Boolean).join('\n\n');
    if (!requestText.trim()) return;
    busy = true; status = 'Starting planner…';
    try {
      const response = await fetch('/api/work-items', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: requestText, ...(source?.plan_id ? { project: source.plan_id } : { workspace_id: project }), idempotency_key: crypto.randomUUID() }) });
      const result = await response.json(); if (!response.ok) throw new Error(result.error ?? 'Could not start plan');
      status = `Plan started: ${result.state}${result.planner_session ? ` · session ${result.planner_session}` : ''}`; await load();
    } catch (error) { status = error instanceof Error ? error.message : 'Could not start plan'; }
    finally { busy = false; }
  }
  async function decide(item: Item, approved: boolean) {
    const response = await fetch(`/api/work-items/${item.id}/decision`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ approved }) });
    const result = await response.json(); if (!response.ok) { status = result.error ?? 'Could not update item'; return; } status = `Work item ${result.state}`; await load();
  }
  function stateTone(value: string) { return value === 'asking' ? 'needs-input' : value === 'planning' ? 'running' : value === 'queued' ? 'success' : value === 'ready' ? 'waiting' : value === 'blocked' ? 'blocked' : 'idle'; }
  function stateLabel(value: string | undefined) { return value === 'asking' ? 'Needs input' : value === 'planning' ? 'Planning' : value === 'ready' ? 'Ready for review' : value === 'queued' ? 'Approved' : value === 'blocked' ? 'Blocked' : value === 'idle' ? 'Idle' : 'Unknown status'; }
  function stateText(item: Item) { return item.state === 'asking' ? 'Waiting for answers' : item.state === 'planning' ? 'Planner is preparing a plan' : item.state === 'ready' ? 'Plan ready for review' : item.state === 'queued' ? 'Approved, orchestrator starting' : item.state === 'blocked' ? 'Work is blocked' : item.state === 'idle' ? 'Waiting to start' : 'Status has not been reported'; }
</script>

<section aria-label="Planning">
  <Card title={`Planning requests · ${items.length}`}>
    {#each items as item}
      <article class="work-item" id={`work-item-${item.id}`}>
        <header><Badge tone={stateTone(item.state)}>{stateLabel(item.state)}</Badge><strong>{item.project}</strong><code title={item.id}>{item.id.slice(0, 8)}</code></header>
        <p>{item.text}</p><p class="muted">{stateText(item)}</p>
        {#if item.state === 'queued' && item.launch_request_id}<p role="status">Orchestrator launch requested</p><p>Request {item.launch_request_id}</p>{/if}
        {#if item.plan_path}<p>Plan: {#if item.plan_id}<a href={`/plans/${encodeURIComponent(item.plan_id)}`}>{item.plan_path}</a>{:else}{item.plan_path}{/if}</p>{/if}
        {#if item.plan_text !== undefined}<details class="plan-content" open={item.state === 'ready'}><summary>Draft plan</summary><pre>{item.plan_text}</pre></details>{/if}
        {#if item.planner_session}<p class="muted">Planner session: {item.planner_session}</p>{/if}
        {#if item.audit?.length}<details><summary>Progress history ({item.audit.length})</summary><ol>{#each item.audit as event}<li><strong>{event.new_state}</strong> · {event.detail}</li>{/each}</ol></details>{/if}
        {#if item.questions?.length}<div class="linked-questions"><strong>Questions</strong>{#each item.questions as question}{#if question.plan_id}<a href={`/plans/${encodeURIComponent(question.plan_id)}`}>{question.payload?.asked ?? question.msg_id}</a>{:else if question.thread_id}<a href={`/threads/${encodeURIComponent(question.thread_id)}`}>{question.payload?.asked ?? question.msg_id}</a>{:else}<span>{question.payload?.asked ?? question.msg_id}</span>{/if}{/each}</div>{/if}
        {#if item.state === 'ready'}<div class="item-actions"><Cluster gap="2"><Button onclick={() => decide(item, true)}>Approve plan</Button><Button variant="secondary" onclick={() => decide(item, false)}>Reject</Button></Cluster></div>{/if}
      </article>
    {:else}<p class="muted">No planning requests yet.</p>{/each}
  </Card>
  <Card title={`Planning requests · ${mailbox.length}`}>
    <p class="muted">Start a plan from a question, then answer it in the plan mail thread.</p>
    <div class="return-list" aria-label="Questions to plan">
      {#each mailbox as item}<div class="return-row"><div><strong>{item.asked || item.subject || item.body || 'Question needs context'}</strong><small>{item.sender} · {item.plan_id ?? 'No plan'}</small></div><Button variant="secondary" disabled={busy} onclick={() => submit(item)}>Plan this</Button></div>
      {:else}<p class="muted">No open questions.</p>{/each}
    </div>
    {#if status}<p class="status" role="status">{status}</p>{/if}
  </Card>
</section>

<style>
  section{display:grid;gap:var(--space-4)}
  .muted{color:var(--text-muted)}
  .status{color:var(--text-secondary);overflow-wrap:anywhere}
  .work-item{padding:var(--space-3) 0;border-top:var(--line) solid var(--border-subtle);display:grid;gap:var(--space-2);min-width:0}
  .work-item header{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}
  .work-item header code{margin-left:auto;color:var(--text-muted);overflow-wrap:anywhere}
  .work-item p{margin:0;overflow-wrap:anywhere}
  .work-item details{color:var(--text-secondary)}
  pre{max-height:var(--textarea-max-height);overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--surface-code);color:var(--text-strong);padding:var(--space-3);border-radius:var(--radius-control)}
  .linked-questions{display:grid;gap:var(--space-2)}
  .return-list{max-height:var(--return-list-max-height);min-height:0;overflow:auto}
  .return-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-2) 0;border-top:var(--line) solid var(--border-subtle);min-height:var(--row-min-h)}
  .return-row>div{min-width:0;display:grid;gap:var(--space-1)}
  .return-row strong,.return-row small{overflow-wrap:anywhere}
  .return-row small{color:var(--text-muted)}
  @media(max-width:760px){.return-row{align-items:flex-start}}
</style>
