<script lang="ts">
  import { onMount } from 'svelte';
  import { Badge, Button } from './ui';
  import GroupChip from './GroupChip.svelte';
  import MergeApproval from './MergeApproval.svelte';
  import { api } from './queue';
  import { awaitingReason, display, doneTasks, idleText, nowLine, otherPlanLine, planBadge, planId, planLabel, groupOf, progressPercent, runningWorkers, taskChip, taskCounts, taskKind, taskNote, taskTitle, tasksOf, type Row } from './plans';
  let { plan, open = false, waiting = false, onOpenChange }: { plan: Row; open?: boolean; waiting?: boolean; onOpenChange?: (id: string, open: boolean) => void } = $props();
  const id = $derived(planId(plan));
  const approvalPlan = $derived({ ...plan, id });
  const badge = $derived(planBadge(plan));
  const mergeNeedsLanding = $derived(plan.merge_state === 'approved_not_merged');
  const tasks = $derived(tasksOf(plan));
  const workers = $derived(runningWorkers(plan));
  const workerNames = $derived(workers.slice(0, 3).map((worker: Row) => worker.title ?? worker.id).join(', '));
  const moreWorkers = $derived(Math.max(0, workers.length - 3));
  const STALLED_AFTER_SECONDS = 20 * 60;
  const idleLabel = $derived(plan.activity === 'running' && plan.idle_for < STALLED_AFTER_SECONDS ? '' : idleText(plan.idle_for));
  const questionsLabel = $derived(`${plan.open_questions} open ${plan.open_questions === 1 ? 'question' : 'questions'}`);
  const questionsHref = $derived(`/plans/${encodeURIComponent(id)}#mail`);
  const now = $derived(nowLine(plan));
  const awaiting = $derived(awaitingReason(plan));
  let statusFeedback = $state('');
  let statusPending = $state(false);
  let details: HTMLDetailsElement;
  onMount(() => {
    const clearFeedback = (event: Event) => {
      const topics = (event as CustomEvent<{ topics?: string[] }>).detail?.topics ?? [];
      if (topics.includes('orchestrators')) statusFeedback = '';
    };
    window.addEventListener('runner:snapshot', clearFeedback);
    return () => window.removeEventListener('runner:snapshot', clearFeedback);
  });
  function saveOpenChoice() {
    onOpenChange?.(id, details.open);
  }
  async function askForStatus() {
    if (statusPending) return;
    if (!window.confirm(`Ask ${plan.address} for status?`)) return;
    statusPending = true;
    try {
      await api(`/api/orchestrators/${encodeURIComponent(plan.address)}/status`, { method: 'POST' });
      statusFeedback = 'Status requested.';
    } catch {
      statusFeedback = 'Could not request status.';
    } finally {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
      statusPending = false;
      window.setTimeout(() => { statusFeedback = ''; }, 4000);
    }
  }
</script>
{#snippet chev()}<svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9,6 15,12 9,18"/></svg>{/snippet}
<details class="plan" {open} bind:this={details} ontoggle={saveOpenChoice}>
  <summary>
    <div class="top"><span class="name"><strong>{display(planLabel(plan))}</strong><GroupChip name={groupOf(plan)} /></span>{#if !waiting || awaiting}<Badge tone={badge.tone}>{badge.label}</Badge>{/if}{@render chev()}</div>
    {#if awaiting && plan.activity !== 'done'}<p class="reason" title={awaiting}>{awaiting}</p>{/if}
    {#if mergeNeedsLanding}<div class="merge"><Badge tone="stalled">Approved, not merged</Badge></div>{/if}
    {#if waiting && plan.open_questions > 0}<a class="questions" href={questionsHref}>{questionsLabel}</a>{/if}
    {#if tasks.length}<div class="progress" role="progressbar" aria-label={`${id} progress`} aria-valuenow={doneTasks(plan)} aria-valuemin="0" aria-valuemax={tasks.length}><i style={`width:${progressPercent(plan)}%`}></i></div>{/if}
    <div class="sub"><span>{taskCounts(plan)}</span><span>{workers.length ? `${workers.length} ${workers.length === 1 ? 'worker' : 'workers'} running` : ''}</span></div>
    {#each plan.other_plans ?? [] as other (other.id)}<div class="other-plan"><span aria-hidden="true">↳</span> {otherPlanLine(other)}</div>{/each}
  </summary>
  <div class="body">
    {#if plan.purpose}<p class="purpose">{plan.purpose}</p>{/if}
    <MergeApproval plan={approvalPlan} />
    {#if plan.title && plan.title !== planLabel(plan)}<p class="full-title">{plan.title}</p>{/if}
    {#each tasks as task (task.id)}
      {@const kind = taskKind(task.status)}
      {@const chip = taskChip(task.status)}
      <div class="task">
        <svg class={`st ${kind}`} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          {#if kind === 'done'}<circle cx="12" cy="12" r="9"/><polyline points="8,12.5 11,15.5 16,9"/>{:else if kind === 'run'}<circle cx="12" cy="12" r="9" opacity=".3"/><path d="M12 3a9 9 0 0 1 9 9"/>{:else if kind === 'wait'}<circle cx="12" cy="12" r="9"/><polyline points="12,7 12,12 15.5,14"/>{:else if kind === 'block'}<circle cx="12" cy="12" r="9"/><line x1="12" y1="7" x2="12" y2="13"/><line x1="12" y1="16.5" x2="12" y2="16.6"/>{:else}<circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>{/if}
        </svg>
        <span class="n">{taskTitle(task)}</span><small>{taskNote(task)}</small><Badge tone={chip.tone}>{chip.label}</Badge>
      </div>
    {/each}
    {#if now && now !== 'unknown'}<div class="now"><b>Now:</b> {now}</div>{/if}
    {#if idleLabel}<p class="muted">{idleLabel}</p>{/if}
    {#if workers.length}<p class="muted">Working: {workerNames}{#if moreWorkers}, +{moreWorkers} more{/if}</p>{/if}
    {#if !waiting && plan.open_questions > 0}<a class="questions" href={questionsHref}>{questionsLabel}</a>{/if}
    {#if plan.plan_joined !== false}<Button href={`/plans/${encodeURIComponent(id)}`} variant="secondary" class="block">Open plan</Button>{/if}
    {#if plan.can_ask_status}<Button variant="secondary" class="block" disabled={statusPending} onclick={askForStatus}>{statusPending ? 'Requesting status…' : 'Ask for status'}</Button>{/if}
    {#if statusFeedback}<p class="muted" role="status">{statusFeedback}</p>{/if}
  </div>
</details>
<style>
  .plan{border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);box-shadow:var(--elevation-card);min-width:0}
  summary{list-style:none;cursor:pointer}summary::-webkit-details-marker{display:none}
  .plan>summary{display:grid;gap:var(--space-2);padding:var(--space-4);min-height:var(--control-h)}
  .top{display:flex;align-items:center;gap:var(--space-2);min-width:0}
  .reason{margin:0;color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .merge{display:flex;min-width:0}
  .name{display:flex;flex:1;flex-wrap:wrap;align-items:center;gap:var(--space-1) var(--space-2);min-width:0}
  .full-title{margin:0;color:var(--text-secondary);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .purpose{margin:0;color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .top strong{min-width:0;color:var(--text-strong);overflow-wrap:anywhere}
  .chev{flex:none;color:var(--text-muted)}
  .chev polyline{transform-origin:12px 12px;transition:transform .15s}
  details[open]>summary .chev polyline{transform:rotate(90deg)}
  .progress{height:var(--space-2);border-radius:var(--radius-pill);background:var(--surface-inset);overflow:hidden}
  .progress>i{display:block;height:100%;background:var(--accent);border-radius:var(--radius-pill)}
  .sub{display:flex;flex-wrap:wrap;justify-content:space-between;gap:var(--space-1) var(--space-2);color:var(--text-muted);font-size:var(--font-size-xs)}
  .other-plan{padding-left:var(--space-3);color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .body{display:grid;gap:var(--space-3);padding:var(--space-3) var(--space-4) var(--space-4);border-top:var(--line) solid var(--border-subtle)}
  .muted{margin:0;color:var(--text-muted);font-size:var(--font-size-xs)}
  .questions{display:flex;align-items:center;min-height:var(--control-h);color:var(--accent);font-weight:650;text-decoration:none}
  .st{flex:none}
  .st.done{color:var(--text-success)}.st.run{color:var(--accent)}.st.wait{color:var(--text-waiting)}.st.pend{color:var(--text-subtle)}.st.block{color:var(--text-blocked)}
  .task{display:flex;align-items:center;gap:var(--space-2);min-height:var(--control-h);min-width:0}
  .task .n{flex:1;min-width:0;overflow-wrap:anywhere}
  .task small{color:var(--text-muted);font-size:var(--font-size-xs);flex:none}
  .now{padding:var(--space-2) var(--space-3);border-radius:var(--radius-control);background:var(--surface-accent);color:var(--text-secondary);font-size:var(--font-size-xs)}
  .body>:global(.block){width:100%}
</style>
