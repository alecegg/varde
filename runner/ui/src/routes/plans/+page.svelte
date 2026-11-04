<script lang="ts">
  import { onMount } from 'svelte';
  import { refreshWhenVisible } from '../../lib/refresh';
  import { onSnapshot } from '../../lib/mail/thread';
  import { cacheRead, cacheWrite } from '../../lib/cache';
  import { getConnectionStatus } from '../../lib/connection';
  import { api } from '../../lib/queue';
  import type { QueueCategory } from '../../lib/queue';
  import { groupPlans, type PlanListItem } from '../../lib/plans';
  import { Badge, Button, Card, EmptyState, GroupHeader, Row, StatusPill } from '../../lib/ui';
  import Skeleton from '../../lib/ui/Skeleton.svelte';
  import DragHandle from '../../lib/DragHandle.svelte';
  import { persistQueueOrder, queueMoveAnnouncement, reorderQueue } from './queueOrder';
  import { visibleQueue } from './visibleQueue';

  const REQUEST_TIMEOUT_MS = 15_000;
  const PLANS_LOAD_ERROR = 'Could not load plans. Check your connection and retry.';
  const PLAN_CACHE_KEY = 'varde:cache:plans:v1';
  const CACHE_MAX_AGE_MS = 10 * 60 * 1000;
  let plans = $state<PlanListItem[]>([]);
  let error = $state('');
  let queueError = $state('');
  let queueUpdating = $state(false);
  let queueAnnouncement = $state('');
  let queueCategories = $state<QueueCategory[]>([]);
  let loading = $state(true);
  let requestSequence = 0;
  let fallback: ReturnType<typeof setInterval> | undefined;
  let groups = $derived(groupPlans(plans));
  let showAllQueued = $state(false);
  let queuedToShow = $derived(visibleQueue(groups.queued, showAllQueued));

  async function loadPlans() {
    const sequence = ++requestSequence;
    try {
      const data = await api<PlanListItem[]>('/api/plans', undefined, REQUEST_TIMEOUT_MS);
      if (sequence !== requestSequence) return;
      plans = data;
      error = '';
      cacheWrite(PLAN_CACHE_KEY, plans);
      loading = false;
      const queueSnapshot = await api<{ categories: QueueCategory[] }>('/api/queue', undefined, REQUEST_TIMEOUT_MS).catch(() => null);
      if (sequence === requestSequence && queueSnapshot) queueCategories = queueSnapshot.categories ?? [];
    } catch {
      if (sequence === requestSequence) error = PLANS_LOAD_ERROR;
    } finally {
      if (sequence === requestSequence) loading = false;
    }
  }

  function retry() {
    error = '';
    loading = plans.length === 0;
    void loadPlans();
  }

  function queueCategory(id: string) {
    return queueCategories.find((category) => category.waiting.some((plan) => plan.id === id));
  }

  function queueIndex(id: string) {
    return queueCategory(id)?.waiting.findIndex((plan) => plan.id === id) ?? -1;
  }

  function queueMoveDisabled(id: string, index: number, direction: 'up' | 'down', categoryId?: string) {
    if (queueUpdating || !categoryId) return true;
    const lastIndex = (queueCategory(id)?.waiting.length ?? 0) - 1;
    return direction === 'up' ? index === 0 : index === lastIndex;
  }

  function moveQueueRow(id: string, index: number, categoryId: string | undefined, direction: 'up' | 'down') {
    if (!categoryId) return;
    const targetIndex = index + (direction === 'up' ? -1 : 1);
    void reorderPlans(categoryId, index, targetIndex, direction);
  }

  async function reorderPlans(categoryId: string, fromIndex: number, toIndex: number, direction: 'up' | 'down') {
    if (queueUpdating) return;
    const previousCategories = queueCategories;
    const previousPlans = plans;
    const category = previousCategories.find((item) => item.id === categoryId);
    if (!category) return;
    const previousIds = category.waiting.map((plan) => plan.id);
    const nextIds = reorderQueue(previousIds, fromIndex, toIndex);
    if (nextIds.every((id, index) => id === previousIds[index])) return;
    const movedId = previousIds[fromIndex];
    const movedPlan = category.waiting[fromIndex];

    const waitingById = new Map(category.waiting.map((plan) => [plan.id, plan]));
    queueCategories = previousCategories.map((item) => item.id === categoryId
      ? { ...item, waiting: nextIds.flatMap((id) => waitingById.has(id) ? [waitingById.get(id)!] : []) }
      : item);
    const positions = new Map(queueCategories.flatMap((item) => item.waiting.map((plan) => plan.id)).map((id, index) => [id, index + 1]));
    plans = plans.map((plan) => positions.has(plan.id) ? { ...plan, queue_position: positions.get(plan.id)! } : plan);
    queueError = '';
    queueUpdating = true;
    try {
      await persistQueueOrder(previousIds, nextIds);
      cacheWrite(PLAN_CACHE_KEY, plans);
      queueAnnouncement = queueMoveAnnouncement(movedPlan?.label || movedPlan?.title || movedId, toIndex + 1, nextIds.length);
    } catch {
      queueCategories = previousCategories;
      plans = previousPlans;
      await loadPlans();
      queueError = 'Could not save the queue order. The list has been refreshed.';
    } finally {
      queueUpdating = false;
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-plan-id="${CSS.escape(movedId)}"] .move[data-direction="${direction}"]`)?.focus());
    }
  }

  function startFallback() {
    fallback ??= setInterval(loadPlans, 3000);
  }

  function stopFallback() {
    if (fallback) clearInterval(fallback);
    fallback = undefined;
  }

  function connectionChanged(event: Event) {
    const healthy = (event as CustomEvent<string>).detail === 'healthy';
    if (healthy) {
      stopFallback();
    } else {
      startFallback();
    }
  }

  function statusLabel(status: PlanListItem['status']) {
    return status === 'in_progress' ? 'In progress' : status === 'needs_review' ? 'Needs review' : status === 'blocked' ? 'Blocked' : status === 'queued' ? 'Queued' : 'Done';
  }

  function statusTone(status: PlanListItem['status']) {
    return status === 'in_progress' ? 'running' : status === 'queued' ? 'waiting' : status === 'done' ? 'success' : 'blocked';
  }

  function updatedLabel(value: string) {
    const timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp)) return 'Updated time unavailable';
    return `Updated ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)}`;
  }

  onMount(() => {
    plans = cacheRead<PlanListItem[]>(PLAN_CACHE_KEY, CACHE_MAX_AGE_MS) ?? [];
    loading = plans.length === 0;
    const stopSnapshot = onSnapshot(['plans'], loadPlans);
    const stopVisibleRefresh = refreshWhenVisible(loadPlans);
    window.addEventListener('runner:connection', connectionChanged);
    if (getConnectionStatus() !== 'healthy') startFallback();
    void loadPlans();
    return () => {
      stopSnapshot();
      stopVisibleRefresh();
      stopFallback();
      window.removeEventListener('runner:connection', connectionChanged);
    };
  });
</script>

<svelte:head><title>Varde Runner · Plans</title></svelte:head>
<div class="page plans-page">
  <p class="visually-hidden" role="status">{queueAnnouncement}</p>
  {#if loading && !plans.length}<div class="summary-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>{:else}<p class="summary">{[
    groups.inProgress.length && `${groups.inProgress.length} in progress`,
    groups.queued.length && `${groups.queued.length} queued`,
    groups.blocked.length && `${groups.blocked.length} blocked`,
    groups.needsReview.length && `${groups.needsReview.length} need review`
  ].filter(Boolean).join(' · ')}</p>{/if}
  {#if error}<div role="alert" class="error"><p>{error}</p><Button variant="secondary" onclick={retry}>Retry</Button></div>{/if}
  {#if queueError}<div class="toast" role="alert"><span>{queueError}</span><Button variant="secondary" onclick={() => queueError = ''}>Dismiss</Button></div>{/if}
  {#if groups.inProgress.length}
    <section aria-label="In progress">
      <GroupHeader title="In progress" count={groups.inProgress.length} />
      <Card><div class="rows">{#each groups.inProgress as plan (plan.id)}{@render planRow(plan)}{/each}</div></Card>
    </section>
  {/if}
  <section aria-label="Queue">
    {#if loading && !plans.length}<div class="loading-group-header"><h2>Queue</h2></div>{:else}<GroupHeader title="Queue" count={groups.queued.length} />{/if}
    <Card>
      {#if groups.queued.length}<div class="rows">{#each queuedToShow as plan, index (plan.id)}{@render planRow(plan, queueCategory(plan.id)?.id, queueIndex(plan.id), index)}{/each}</div>
        {#if groups.queued.length > 20}<Button variant="secondary" onclick={() => showAllQueued = !showAllQueued}>{showAllQueued ? 'Show fewer' : `Show more (${groups.queued.length - 20})`}</Button>{/if}
      {:else if loading}<div aria-busy="true"><Skeleton rows={20} class="queue-loading" /></div>
      {:else if !error}<EmptyState title="No plans are queued" description="New plans will appear here when they are ready." />{/if}
    </Card>
  </section>
  {#if groups.blocked.length}
    <section aria-label="Blocked">
      <GroupHeader title="Blocked" count={groups.blocked.length} />
      <Card><div class="rows">{#each groups.blocked as plan (plan.id)}{@render planRow(plan)}{/each}</div></Card>
    </section>
  {/if}
  {#if groups.needsReview.length}
    <section aria-label="Needs review">
      <GroupHeader title="Needs review" count={groups.needsReview.length} />
      <Card><div class="rows">{#each groups.needsReview as plan (plan.id)}{@render planRow(plan)}{/each}</div></Card>
    </section>
  {/if}
  {#if groups.done.length}
    <details class="done">
      <summary><h2>Recently done</h2><span class="count">{groups.done.length} completed</span><span class="chevron" aria-hidden="true">›</span></summary>
      <Card><div class="rows">{#each groups.done as plan (plan.id)}{@render planRow(plan)}{/each}</div></Card>
    </details>
  {/if}
</div>

{#snippet planRow(plan: PlanListItem, categoryId?: string, index?: number, fallbackIndex?: number)}
  {@const rowIndex = index ?? fallbackIndex}
  {@const rowCategoryId = categoryId ?? 'queued'}
  <div class:queued={rowIndex !== undefined} data-agent-index={rowIndex} data-pin-group={rowCategoryId} data-plan-id={plan.id}>
  <Row href={`/plans/${encodeURIComponent(plan.id)}`} title={plan.label || plan.title || plan.id} meta={`${updatedLabel(plan.updated)}${plan.open_comments ? ` · ${plan.open_comments} open ${plan.open_comments === 1 ? 'comment' : 'comments'}` : ''}`}>
    {#snippet chips()}
      {#if plan.status !== 'in_progress' && !(rowIndex !== undefined && plan.status === 'queued') && plan.status !== 'needs_review'}<StatusPill status={plan.status} tone={statusTone(plan.status)} />{/if}
    {/snippet}
    {#snippet trailing()}
      {#if rowIndex !== undefined}
        <DragHandle index={rowIndex} onreorder={(target) => { if (categoryId && target.group === categoryId) reorderPlans(categoryId, rowIndex, target.index, target.index < rowIndex ? 'up' : 'down'); }} />
        <button type="button" class="move" class:boundary-disabled={queueMoveDisabled(plan.id, rowIndex, 'up', categoryId)} data-direction="up" aria-label={`Move ${plan.label || plan.title || plan.id} up`} title="Move up" aria-disabled={queueMoveDisabled(plan.id, rowIndex, 'up', categoryId)} disabled={queueMoveDisabled(plan.id, rowIndex, 'up', categoryId)} onclick={() => moveQueueRow(plan.id, rowIndex, categoryId, 'up')}>↑</button>
        <button type="button" class="move" class:boundary-disabled={queueMoveDisabled(plan.id, rowIndex, 'down', categoryId)} data-direction="down" aria-label={`Move ${plan.label || plan.title || plan.id} down`} title="Move down" aria-disabled={queueMoveDisabled(plan.id, rowIndex, 'down', categoryId)} disabled={queueMoveDisabled(plan.id, rowIndex, 'down', categoryId)} onclick={() => moveQueueRow(plan.id, rowIndex, categoryId, 'down')}>↓</button>
      {/if}
    {/snippet}
  </Row>
  </div>
{/snippet}

<style>
  .page{display:grid;gap:var(--space-4);min-width:0}
  .summary{margin:0;color:var(--text-muted)}.summary-skeleton{display:flex;align-items:center;gap:var(--space-2);min-height:var(--font-size-lg)}.summary-skeleton span{width:var(--space-6);height:var(--space-2);border-radius:var(--radius-control);background:var(--surface-1)}
  .loading-group-header{display:flex;align-items:center;min-height:var(--control-h);padding:0 var(--space-4)}
  .loading-group-header h2{margin:0;color:var(--text-strong);font-size:var(--font-size-md)}
  .page > section,.rows{width:100%;min-width:0}
  :global(.queue-loading){--skeleton-row-h:90px}
  @media(max-width:600px){:global(.queue-loading){--skeleton-row-h:150px}}
  .queued{min-width:0}
  .move{display:grid;place-items:center;flex:none;width:var(--control-h);min-width:var(--control-h);min-height:var(--control-h);padding:0;border:var(--line) solid var(--border-subtle);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);font-family:inherit;font-size:inherit;line-height:inherit;cursor:pointer}
  .move:disabled,.move[aria-disabled="true"]{opacity:1;background:var(--surface-disabled);border-color:var(--border-strong);color:var(--text-secondary);cursor:not-allowed}
  .move.boundary-disabled{opacity:1;filter:none;background:var(--surface-disabled);border-color:var(--border-strong);color:var(--text-secondary)}
  .move:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
  :global(.queued .row){align-items:center;gap:var(--space-2)}
  :global(.queued .row > .copy){align-self:center;min-height:var(--control-h)}
  :global(.queued .row > .copy .title){display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
  :global(.queued .row > .copy .meta){display:none}
  :global(.queued .row > .copy .chips){margin-top:var(--space-1)}
  :global(.queued .row > .trailing){gap:var(--space-1)}
  section{min-width:0}
  .rows{min-width:0}
  .error{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-3);margin:0;padding:var(--space-3);border-radius:var(--radius-control);background:var(--status-blocked-bg);color:var(--status-blocked-fg)}
  .error p{margin:0;min-width:0;overflow-wrap:anywhere}
  .empty{margin:0;color:var(--text-muted);font-size:var(--font-size-sm)}
  .done{min-width:0}
  .done summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:var(--space-1);min-width:0;min-height:calc(var(--control-h) + var(--space-1));padding:0;list-style:none;cursor:pointer}
  .done summary::-webkit-details-marker{display:none}
  .done h2{min-width:0;max-width:calc(100% - 6rem);margin:0;color:var(--text-strong);font-size:var(--font-size-md);overflow-wrap:anywhere}
  .count{color:var(--text-muted);font-size:var(--font-size-xs)}
  .chevron{color:var(--text-muted);font-size:var(--font-size-lg);line-height:1}
  .done[open] .chevron{transform:rotate(90deg)}
  .toast{position:fixed;z-index:20;right:var(--space-4);bottom:var(--space-4);display:flex;align-items:center;gap:var(--space-3);max-width:min(32rem,calc(100vw - 2 * var(--space-4)));padding:var(--space-3);border:var(--line) solid var(--status-blocked-fg);border-radius:var(--radius-card);background:var(--surface-1);color:var(--text-body);box-shadow:var(--elevation-card)}
  @media(min-width:900px){:global(.shell-body:has(.plans-page) > .shell-content){flex:1}}
  @media(min-width:900px){.page{width:100%;box-sizing:border-box;padding:var(--space-4)}}
  @media(min-width:1024px){.plans-page{width:min(100%,880px);margin-inline:auto}}
</style>
