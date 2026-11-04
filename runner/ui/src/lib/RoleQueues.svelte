<script lang="ts">
  import { Badge, Card, StatusPill } from './ui';
  import { blockedReason, budgetPercent, budgetTone, duration, expiryLabel, itemTone, type RoleQueuesData } from './roleQueues';

  let { data }: { data: RoleQueuesData } = $props();

  const states = $derived(new Map(data.roles.flatMap((lane) => lane.items.map((item) => [item.id, item.state] as const))));

  function budgetRows(): { label: string; value: number | undefined; limit: number; unit?: string; fraction: boolean }[] {
    const snapshot = data.budget.snapshot;
    const limits = data.budget.limits;
    if (!snapshot || !limits) return [];
    return [
      { label: 'Workers', value: snapshot.live_workers, limit: limits.global_worker_ceiling, fraction: false },
      { label: 'Memory', value: snapshot.rss_mb, limit: limits.rss_mb_max, unit: ' MB', fraction: false },
      { label: 'CPU', value: snapshot.cpu_pct, limit: limits.cpu_pct_max, unit: '%', fraction: false },
      { label: 'Processes', value: snapshot.processes, limit: limits.processes_max, fraction: false },
      ...Object.entries(limits.provider_max).map(([provider, limit]) => ({ label: provider, value: snapshot.providers[provider], limit, unit: '%' as const, fraction: true })),
    ];
  }

  function queueState(state: string): 'queued' | 'claimed' | 'building' | 'in_review' | 'merged' | 'failed' | 'unknown' {
    if (state === 'queued' || state === 'claimed' || state === 'building' || state === 'in_review' || state === 'merged' || state === 'failed') return state;
    return 'unknown';
  }
</script>

<Card title="Role queues">
  <section class="budget" aria-label="Global resource budget">
    <div class="budget-heading"><strong>Start budget</strong><Badge tone={budgetTone(data.budget.decision.ok)}>{data.budget.decision.reason}</Badge></div>
    {#if budgetRows().length}
      {#each budgetRows() as row (row.label)}
        {@const percent = budgetPercent(row.fraction ? (row.value == null ? undefined : row.value * 100) : row.value, row.fraction ? row.limit * 100 : row.limit)}
        <div class="budget-row">
          <span>{row.label}</span><span>{row.value == null ? '—' : `${row.fraction ? Math.round(row.value * 100) : row.value}${row.unit ?? ''} / ${row.fraction ? Math.round(row.limit * 100) : row.limit}${row.unit ?? ''}`}</span>
          <progress aria-label={`${row.label} budget`} max="100" value={percent ?? 0}></progress>
        </div>
      {/each}
    {:else}<p class="muted">Resource snapshot or limits unavailable.</p>{/if}
  </section>

  <div class="lanes">
    {#each data.roles as lane (lane.role)}
      <section class="lane" aria-label={`${lane.role} queue`}>
        <header><h3>{lane.role}</h3><span>{lane.queued} queued · {lane.claimed} claimed · {lane.ready} ready</span></header>
        {#each lane.items as item (item.id)}
          {@const reason = blockedReason(item, states)}
          <article class="item">
            <div class="item-title"><strong>{item.id}</strong>{#if reason}<Badge tone="blocked">Blocked</Badge>{:else}<StatusPill status={queueState(item.state)} tone={itemTone(item, reason)} />{/if}</div>
            {#if item.claimed_by}<p>Claimed by {item.claimed_by} · {expiryLabel(item.claim_expires_at)}</p>{/if}
            {#if reason}<p class="blocked">{reason}</p>{/if}
            <p>Cycle {duration(data.metrics.cycle_seconds[item.id])}</p>
          </article>
        {:else}<p class="muted">No items in this lane.</p>{/each}
      </section>
    {:else}<p class="muted">No role queues yet.</p>{/each}
  </div>
  <section class="idle"><h3>Idle by lane</h3>
    {#each Object.entries(data.metrics.idle_seconds) as [slot, seconds] (slot)}<p>{slot} · {duration(seconds)}</p>
    {:else}<p class="muted">No idle time recorded.</p>{/each}
  </section>
</Card>

<style>
  .budget,.lane,.idle{padding-block:var(--space-2);border-bottom:var(--line) solid var(--border-subtle)}
  .budget-heading,.budget-row,.item-title,header{display:flex;justify-content:space-between;align-items:center;gap:var(--space-2)}
  .budget-row{display:grid;grid-template-columns:1fr auto;gap:var(--space-1) var(--space-2);padding-top:var(--space-2);font-size:var(--font-size-xs)}
  progress{grid-column:1/-1;width:100%;height:var(--space-2);accent-color:var(--accent)}
  h3{margin:0;font-size:var(--font-size-sm);text-transform:capitalize}
  header span,.muted,.item p{color:var(--text-muted);font-size:var(--font-size-xs)}
  .item{padding:var(--space-2) 0;border-top:var(--line) solid var(--border-subtle)}
  .item p{margin:var(--space-1) 0 0;overflow-wrap:anywhere}
  .blocked{color:var(--color-danger,var(--text-danger))}
  .idle p{margin:var(--space-1) 0;color:var(--text-muted);font-size:var(--font-size-xs)}
  .muted{margin:var(--space-2) 0}
</style>
