<script lang="ts">
  import { onMount } from 'svelte';
  import { criterionPresentation, reportLoadMessage, requestStateForStatus, streakPresentation, type MailSoakReport } from './mailSoak';
  import { Card, StatusPill } from './ui';

  let report = $state<MailSoakReport | null>(null);
  let loadState = $state<'loading' | 'missing' | 'error'>('loading');

  onMount(() => {
    let active = true;
    fetch('/api/mail-soak', { cache: 'no-store', signal: AbortSignal.timeout(15_000) })
      .then(async (response) => {
        const state = requestStateForStatus(response.status);
        if (state === 'missing') { if (active) loadState = 'missing'; return; }
        if (state === 'error') throw new Error(`Request failed (${response.status})`);
        const data = await response.json() as MailSoakReport;
        if (active) report = data;
      })
      .catch(() => { if (active) loadState = 'error'; });
    return () => { active = false; };
  });
</script>

<Card title="Mail reliability soak">
  {#if report}
    <p class="summary">{streakPresentation(report)} · {report.active_orchestrators} active {report.active_orchestrators === 1 ? 'orchestrator' : 'orchestrators'} · {report.date}</p>
    {#if report.undeliverable}<p class="note">{report.undeliverable} {report.undeliverable === 1 ? 'message could not' : 'messages could not'} be delivered in this period</p>{/if}
    <ul aria-label="Mail soak criteria">
      {#each report.criteria as criterion (criterion.id)}
        {@const presentation = criterionPresentation(criterion)}
        <li>
          <span class="label">{presentation.label}</span>
          {#if criterion.id === 'delivered-latency'}<span class="note" title="95% of delivered messages arrive within this time.">95% of delivered messages arrive within this time.</span>{/if}
          <span class="measure">{presentation.measure}</span>
          <span class="metric-status">
            {#if criterion.insufficient}
              <StatusPill status="idle" tone="idle" label={presentation.status} />
            {:else if criterion.ok}
              <StatusPill status="success" tone="success" label={presentation.status} />
            {:else}
              <StatusPill status="failed" tone="blocked" label={presentation.status} />
            {/if}
          </span>
          {#if presentation.note}<span class="note">{presentation.note}</span>{/if}
        </li>
      {/each}
    </ul>
  {:else if loadState === 'missing'}
    <p class="summary">{reportLoadMessage(loadState)}</p>
  {:else if loadState === 'error'}
    <p class="error" role="alert">{reportLoadMessage(loadState)}</p>
  {:else}
    <p class="summary">Loading mail soak report…</p>
  {/if}
</Card>

<style>
  .summary{margin:0;color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  ul{list-style:none;padding:0;margin:var(--space-2) 0 0}
  li{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:var(--space-2);min-height:var(--row-min-h);border-top:var(--line) solid var(--border-subtle)}
  .label{min-width:0;overflow-wrap:anywhere}
  .metric-status{justify-self:end}
  .measure{color:var(--text-muted);font-size:var(--font-size-sm);text-align:right;overflow-wrap:anywhere}
  .note{grid-column:1/-1;color:var(--text-muted);font-size:var(--font-size-xs)}
  .error{margin:0;color:var(--status-blocked-fg);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  @media(max-width:420px){li{grid-template-columns:minmax(0,1fr) auto}.metric-status{grid-column:2;grid-row:1}.measure{grid-row:2;grid-column:1;text-align:left}}
</style>
