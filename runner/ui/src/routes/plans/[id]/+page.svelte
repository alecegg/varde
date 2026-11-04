<script lang="ts">
  import { onMount } from 'svelte';
  import { tick } from 'svelte';
  import { page } from '$app/state';
  import { api, type PlanDetail } from '../../../lib/queue';
  import { refreshWhenVisible } from '../../../lib/refresh';
  import { onSnapshot } from '../../../lib/mail/thread';
  import { taskChip } from '../../../lib/plans';
  import { getPlanThreads, listInstanceWorkspaces, threadsForTask, type InstanceThread } from '../../../lib/threadsApi';
  import { addPlanComment, commentKind, commentState, setPlanCommentState } from '../../../lib/planComments';
  import GroupChip from '../../../lib/GroupChip.svelte';
  import TaskQueue from '../../../lib/TaskQueue.svelte';
  import PlanMail from '../../../lib/mail/PlanMail.svelte';
  import MergeApproval from '../../../lib/MergeApproval.svelte';
  import ActorBadge from '../../../lib/ActorBadge.svelte';
  import { Badge, Button, Card, Markdown, StatusPill } from '../../../lib/ui';
  import ChatHeader from '../../../lib/ChatHeader.svelte';
  import { cacheRead, cacheWrite } from '../../../lib/cache';
  import Skeleton from '../../../lib/ui/Skeleton.svelte';

  let plan = $state<PlanDetail | null>(null);
  let approvalPlan = $state<(Record<string, any> & { id: string }) | null>(null);
  let instances = $state<InstanceThread[]>([]);
  let workspaces = $state<Record<string, string>>({});
  let error = $state('');
  let loading = $state(true);
  let sendError = $state('');
  let hasMail = $state(false);
  let mailChecked = $state(false);
  let target = $state('plan');
  let text = $state('');
  let sending = $state(false);
  let composerOpen = $state(false);
  let updating = $state<string | null>(null);
  let commentStatus = $state('');
  const planId = $derived(page.params.id ?? '');

  async function load() {
    if (!planId) { error = 'Plan not found'; return; }
    const key = `varde:cache:plan-detail:${encodeURIComponent(planId)}:v1`;
    if (!plan) {
      const cached = cacheRead<PlanDetail>(key, 10 * 60 * 1000);
      if (cached) { plan = cached; loading = false; }
    }
    try { plan = await api<PlanDetail>(`/api/plans/${encodeURIComponent(planId)}`); cacheWrite(key, plan); error = ''; }
    catch (e) { error = e instanceof Error ? e.message : 'Could not load plan'; }
    finally { loading = false; }
  }
  async function comment() {
    if (!plan || !text.trim()) return;
    sending = true; sendError = '';
    try {
      const result = await addPlanComment(plan.id, target, text);
      plan.comments = [...plan.comments, result.comment as PlanDetail['comments'][number]];
      commentStatus = 'Delivered';
      text = '';
      composerOpen = false;
      await focusCommentTrigger();
    } catch (e) { sendError = e instanceof Error ? e.message : 'Could not send comment'; }
    finally { sending = false; }
  }
  function openComment(targetId = 'plan') {
    target = targetId;
    composerOpen = true;
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('#comment-text')?.focus());
  }
  function closeComment() {
    if (sending) return;
    composerOpen = false;
    sendError = '';
    void focusCommentTrigger();
  }
  function cancelComment() {
    text = '';
    closeComment();
  }
  async function focusCommentTrigger() {
    await tick();
    document.querySelector<HTMLButtonElement>('.comment-trigger')?.focus();
  }
  async function toggleComment(item: { id: string; state: string }) {
    if (!plan) return;
    updating = item.id; error = '';
    try {
      const state = commentState(item.state) === 'open' ? 'resolved' : 'open';
      const result = await setPlanCommentState(plan.id, item.id, state);
      plan.comments = plan.comments.map((row) => row.id === item.id ? result.comment as PlanDetail['comments'][number] : row);
    } catch (e) { error = e instanceof Error ? e.message : 'Could not update comment'; }
    finally { updating = null; }
  }
  async function loadInstances() { if (!planId) { instances = []; return; } try { instances = await getPlanThreads(planId); } catch { instances = []; } }
  const taskInstances = (task: PlanDetail['tasks'][number]) => threadsForTask(task, instances, workspaces);
  async function loadApprovalPlan() { try { const data = await api<{ plans?: (Record<string, any> & { id: string })[] }>('/api/orchestrators'); approvalPlan = data.plans?.find((item) => item.id === page.params.id) ?? null; } catch { approvalPlan = null; } }
  onMount(() => {
    load(); loadApprovalPlan(); loadInstances();
    listInstanceWorkspaces().then((value) => workspaces = value).catch(() => {});
    const updateViewport = () => document.documentElement.style.setProperty('--reader-vv-height', `${window.visualViewport?.height ?? window.innerHeight}px`);
    updateViewport(); window.visualViewport?.addEventListener('resize', updateViewport);
    const stopSnapshot = onSnapshot(['orchestrators', 'mailbox'], () => { load(); loadApprovalPlan(); loadInstances(); });
    const stopVisibleRefresh = refreshWhenVisible(() => { load(); loadApprovalPlan(); loadInstances(); });
    return () => { window.visualViewport?.removeEventListener('resize', updateViewport); stopVisibleRefresh(); stopSnapshot(); };
  });
</script>

<svelte:head><title>Varde Runner · Plan</title></svelte:head>
<div class="page plan-page">
  <ChatHeader title="Plan" backHref="/plans" backLabel="Back to plans" singleLineTitle />
  {#if error}<p role="alert" class="error">{error}</p>{/if}
  {#if plan}
    <h1 class="plan-title">{plan.title}</h1>
    <div class="facts">{#if hasMail}<Badge tone="needs-input">Needs input</Badge>{/if}{#if plan.group_name}<GroupChip name={plan.group_name} />{/if}{#if plan.notes_status && plan.notes_status !== 'none'}<Badge tone="idle">Notes: {plan.notes_status}</Badge>{/if}{#if plan.review_status && plan.review_status !== 'none'}<Badge tone="idle">Review: {plan.review_status}</Badge>{/if}</div>
    <Card><Markdown text={plan.plan_text} /></Card>
    <PlanMail planId={plan.id} onneedsinput={(value) => { hasMail = value; mailChecked = true; }} />
    {#if approvalPlan}<MergeApproval plan={approvalPlan} needsInput={hasMail || !mailChecked} />{/if}
    <TaskQueue />
    <Card title="Tasks">{#each plan.tasks as task (task.id)}<article class="task"><h3>{task.title}</h3><p class="facts"><Badge tone={taskChip(task.status).tone}>{taskChip(task.status).label}</Badge></p>{#if task.acceptance_criteria.length}<ul>{#each task.acceptance_criteria as criterion}<li>{criterion}</li>{/each}</ul>{/if}{#each taskInstances(task) as instance (instance.agent_id)}<a class="instance" href={`/thread/${encodeURIComponent(instance.agent_id)}`}><span>{instance.label}</span><StatusPill status={instance.state === 'running' ? 'running' : instance.state === 'failed' ? 'failed' : 'unknown'} tone={instance.state === 'running' ? 'running' : instance.state === 'failed' ? 'blocked' : 'idle'} /><time>{instance.last_activity ?? 'No activity yet'}</time></a>{/each}<Button variant="link" onclick={() => openComment(task.id)}>Comment on task</Button></article>{:else}<p class="muted">No task details.</p>{/each}</Card>
    <Card title={`Comments · ${plan.comments.filter((item) => commentState(item.state) === 'open').length} open`}>
      {#each plan.comments as item (item.id)}
        {@const state = commentState(item.state)}
        {@const kind = commentKind(item.kind)}
        <article class="comment">
          <div class="facts"><StatusPill status={state === 'open' ? 'open' : 'resolved'} tone={state === 'open' ? 'waiting' : 'success'} /><Badge tone="idle">{kind === 'delivered' ? 'Delivered' : 'Saved'}</Badge><span>{item.target === 'plan' ? 'Plan' : item.target}</span><ActorBadge actor={item.actor} /></div>
          <p>{item.text}</p>
          {#if item.resolution_note}<p class="muted">Resolution: {item.resolution_note}</p>{/if}
          <div class="comment-resolution"><span>Comment status</span><Button variant="secondary" disabled={updating === item.id} onclick={() => toggleComment(item)}>{updating === item.id ? 'Updating…' : state === 'open' ? 'Resolve' : 'Reopen'}</Button></div>
        </article>
      {:else}<p class="empty">No comments yet. Start a discussion about the plan or a task.</p>{/each}
      <Button class="comment-trigger" variant="secondary" hidden={composerOpen} onclick={() => openComment()}>Add comment</Button>
      <p class="visually-hidden" role="status">{commentStatus}</p>
    </Card>
    {#if composerOpen}<form id="comment-box" class="composer" onsubmit={(event) => { event.preventDefault(); comment(); }}>
      <label for="comment-target">Comment on</label>
      <select id="comment-target" bind:value={target}><option value="plan">Whole plan</option>{#each plan.tasks as task}<option value={task.id}>{task.title}</option>{/each}</select>
      <label for="comment-text">Comment</label>
      <textarea id="comment-text" bind:value={text} placeholder="Ask for clarification or suggest a change" rows="2" onkeydown={(event) => { if (event.key === 'Escape') closeComment(); }}></textarea>
      <div class="send-row"><span>{#if sendError}<span role="alert" class="send-error">{sendError}</span>{/if}</span><div class="composer-actions"><Button variant="secondary" disabled={sending} onclick={cancelComment}>Cancel</Button><Button type="submit" disabled={sending || !text.trim()}>{sending ? 'Sending…' : 'Post comment'}</Button></div></div>
    </form>{/if}
  {:else if loading}<div aria-busy="true"><Skeleton rows={6} card /></div>{/if}
</div>

<style>
  .page{display:grid;gap:var(--space-4);padding-bottom:var(--space-4)}
  .plan-title{margin:0;color:var(--text-strong);font-size:var(--font-size-xl);line-height:1.25;overflow-wrap:anywhere}
  :global(.page > .ui-button){min-height:calc(var(--control-h) + var(--space-1))}
  .facts{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);color:var(--text-muted);font-size:var(--font-size-xs)}
  .task,.comment{display:grid;gap:var(--space-2);padding-block:var(--space-3);border-top:var(--line) solid var(--border-subtle)}
  .instance{display:flex;align-items:center;gap:var(--space-2);min-width:0;min-height:var(--control-h);padding:var(--space-2);border:var(--line) solid var(--border-subtle);border-radius:var(--radius-control);color:var(--text-body);overflow-wrap:anywhere}.instance span{flex:1;min-width:0}.instance time{color:var(--text-muted);font-size:var(--font-size-xs)}
  h3{margin:0;color:var(--text-strong);font-size:var(--font-size-sm);line-height:1.4;overflow-wrap:anywhere}
  .task p,.comment p{margin:0;line-height:1.5;overflow-wrap:anywhere;white-space:pre-wrap;word-break:break-word}
  .task ul{margin:0;padding-left:var(--space-5);display:grid;gap:var(--space-1);line-height:1.45;overflow-wrap:anywhere}
  .muted,.empty{color:var(--text-muted);font-size:var(--font-size-xs)}
  .comment .facts span{font-weight:600;color:var(--text-secondary)}
  .comment-resolution{display:grid;justify-items:start;gap:var(--space-2);padding-top:var(--space-2)}.comment-resolution>span{font-size:var(--font-size-xs);font-weight:650;color:var(--text-muted)}
  .comment :global(.ui-button),.task :global(.ui-button),.composer :global(.ui-button){min-height:calc(var(--control-h) + var(--space-1))}
  .comment :global(.comment-trigger){min-height:44px}
  .error{margin:0;padding:var(--space-3);border-radius:var(--radius-control);background:var(--status-blocked-bg);color:var(--status-blocked-fg)}
  .composer{display:grid;gap:var(--space-2);padding:var(--space-3);border:var(--line) solid var(--border-subtle);border-radius:var(--radius-card);background:var(--surface-1);box-shadow:var(--elevation-card)}
  label{color:var(--text-secondary);font-weight:650}
  select,textarea{width:100%;min-height:var(--control-h);max-width:100%;padding:var(--space-3);font-family:inherit;font-size:inherit;line-height:1.4;color:var(--text-body);background:var(--surface-input);border:var(--line) solid var(--border-control);border-radius:var(--radius-control)}
  #comment-target{box-sizing:border-box;height:calc(var(--control-h) + var(--space-1));min-height:calc(var(--control-h) + var(--space-1));padding-block:0}
  textarea{resize:vertical;min-height:calc(var(--control-h) + var(--space-5));max-height:var(--textarea-max-height)}
  .send-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);min-height:var(--control-h)}.send-row span{color:var(--text-muted);font-size:var(--font-size-xs)}.composer-actions{display:flex;align-items:center;gap:var(--space-2)}
  .send-error{color:var(--status-blocked-fg)!important}
  @media(max-width:600px){textarea{min-height:var(--control-h)}.send-row{align-items:flex-start;flex-direction:column}.composer-actions{width:100%;justify-content:flex-end}}
</style>
