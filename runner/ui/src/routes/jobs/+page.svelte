<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { Badge, Button, Card, PageHeader, StatusPill } from '../../lib/ui';
  import { JOB_POLL_MS, anyJobRunning, displayCost, displayDate, jobCardStatus, jobStateTone, jobStatusLabel, lastRunStatusDiffers, orderJobs, sweepSummary, type Job, type JobRun } from '../../lib/jobs';

  let jobs = $state<Job[]>([]);
  let runs = $state<Record<string, JobRun[]>>({});
  let expanded = $state<Record<string, boolean>>({});
  let budgetDrafts = $state<Record<string, string>>({});
  let loading = $state(true);
  let busy = $state('');
  let error = $state('');
  let poller: ReturnType<typeof setTimeout> | undefined;
  let destroyed = false;

  async function loadJobs(quiet = false) {
    try {
      const response = await fetch('/api/jobs', { cache: 'no-store' });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const data = await response.json() as { jobs: Job[] };
      jobs = orderJobs(data.jobs ?? []);
      if (!quiet) budgetDrafts = Object.fromEntries(jobs.filter((job) => job.run_budget_tokens != null).map((job) => [job.key, String(job.run_budget_tokens)]));
      error = '';
      syncPolling();
    } catch {
      error = 'Could not load scheduled jobs. Check your connection and retry.';
    } finally {
      loading = false;
    }
  }

  function syncPolling() {
    if (destroyed || poller || !anyJobRunning(jobs)) return;
    poller = setTimeout(refreshRunning, JOB_POLL_MS);
  }

  function stopPolling() {
    destroyed = true;
    clearTimeout(poller);
    poller = undefined;
  }

  async function refreshRunning() {
    poller = undefined;
    const running = jobs.filter((job) => job.state === 'running').map((job) => job.key);
    await loadJobs(true);
    for (const key of running) if (expanded[key]) await loadRuns(key);
  }

  async function act(job: Job, action: 'pause' | 'resume' | 'run') {
    busy = `${job.key}:${action}`;
    error = '';
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(job.key)}/${action}`, { method: 'POST' });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      await loadJobs();
      if (action === 'run') await loadRuns(job.key);
    } catch {
      error = `Could not ${action === 'run' ? 'run' : action} ${job.title}. Please retry.`;
    } finally {
      busy = '';
    }
  }

  async function loadRuns(key: string) {
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(key)}/runs?limit=20`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const data = await response.json() as { runs: JobRun[] };
      runs = { ...runs, [key]: data.runs ?? [] };
    } catch {
      error = 'Could not load recent runs. Please retry.';
    }
  }

  async function saveBudget(job: Job, value: string) {
    const budget = Number(value);
    if (!Number.isInteger(budget) || budget < 1 || budget > 10000000) {
      budgetDrafts[job.key] = String(job.run_budget_tokens ?? '');
      error = 'Token budget must be an integer from 1 to 10,000,000.';
      return;
    }
    busy = `${job.key}:budget`;
    error = '';
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(job.key)}/budget`, {
        method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ run_budget_tokens: budget })
      });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      await loadJobs();
    } catch {
      budgetDrafts[job.key] = String(job.run_budget_tokens ?? '');
      error = `Could not save the token budget for ${job.title}. Please retry.`;
    } finally {
      busy = '';
    }
  }

  function entryText(entry: unknown): string {
    return typeof entry === 'string' ? entry : JSON.stringify(entry);
  }

  async function toggleRuns(job: Job) {
    const open = !expanded[job.key];
    expanded = { ...expanded, [job.key]: open };
    if (open && !runs[job.key]) await loadRuns(job.key);
  }

  onMount(() => { loadJobs(); });
  onDestroy(stopPolling);
</script>

<svelte:head><title>Varde Runner · Scheduled jobs</title></svelte:head>
<div class="page">
  <PageHeader title="Scheduled jobs" description="Daily runner jobs and their recent outcomes." />
  {#if error}<p class="error" role="alert">{error} <button type="button" onclick={() => loadJobs()}>Retry</button></p>{/if}
  {#if loading}
    <Card><p class="muted">Loading scheduled jobs…</p></Card>
  {:else if !jobs.length}
    <Card><p class="muted">No scheduled jobs are registered.</p></Card>
  {:else}
    {#each jobs as job (job.key)}
      {@const cardStatus = jobCardStatus(job)}
      <Card>
        <article class="job">
          <div class="heading">
            <h2>{job.title}</h2>
            <StatusPill status={cardStatus.status} label={cardStatus.label} tone={jobStateTone(job.state)} />
          </div>
          <dl class="details">
            {#if job.enabled}<div><dt>Next run</dt><dd>{displayDate(job.next_run_at)}</dd></div>{/if}
            <div><dt>Last run</dt><dd>{#if job.last_run}{#if lastRunStatusDiffers(job)}<StatusPill status={jobStatusLabel(job.last_run.outcome)} tone={jobStateTone(job.last_run.outcome)} />{/if}{#if job.last_run.finished_at}{#if lastRunStatusDiffers(job)} · {/if}{displayDate(job.last_run.finished_at)}{/if}{:else}No runs yet{/if}</dd></div>
          </dl>
          {#if job.last_run?.error}<p class="run-error">{job.last_run.error}</p>{/if}
          {#if job.spends_model_usage}
            <div class="usage"><Badge>Uses model usage</Badge>{#if job.run_budget_tokens != null}<label class="budget-field"><span>Token budget</span><span class="budget-input"><input aria-label="Token budget" type="text" inputmode="numeric" pattern="[0-9]*" aria-describedby={`budget-help-${job.key}`} disabled={busy !== ''} value={budgetDrafts[job.key] ?? String(job.run_budget_tokens)} oninput={(event) => budgetDrafts[job.key] = event.currentTarget.value} onchange={(event) => saveBudget(job, event.currentTarget.value)} /><span>tokens per run</span></span><small id={`budget-help-${job.key}`}>From 1 to 10,000,000.</small></label>{/if}{#if job.last_run?.model_tokens != null}<span>Last tokens: {job.last_run.model_tokens}</span>{/if}{#if job.last_run?.cost_usd != null}<span>Estimated last cost: {displayCost(job.last_run.cost_usd)}</span>{/if}</div>
            {#if job.key === 'review' && !job.enabled}<p class="muted">Enabling this job spends model usage within the token budget.</p>{/if}
            {#if job.key === 'review'}
              {#if job.budget_exhausted}<p class="muted">This run exhausted its token budget; remaining sessions stay queued.</p>{/if}
              {#if job.coverage}<p class="muted">Coverage: {job.coverage.analyzed} analyzed of {job.coverage.found} found · {job.coverage.skipped} skipped · {job.coverage.failed} failed · {job.coverage.pending} pending.</p>{/if}
              {#if job.stop_reason}<p class="muted">Stopped: {job.stop_reason}</p>{/if}
            {/if}
          {/if}
          {#if job.key === 'sweep'}
            <p class="muted">{sweepSummary(job.warnings.length, job.failures.length)}</p>
            {#if job.summary_error}<p class="muted">Summary note: {job.summary_error}</p>{/if}
            {#if job.warnings.length || job.failures.length}
              <details><summary>Sweep details</summary><ul class="job-details">{#each job.warnings as item}<li>Warning: {entryText(item)}</li>{/each}{#each job.failures as item}<li>Session failure: {entryText(item)}</li>{/each}</ul></details>
            {/if}
          {/if}
          <div class="actions">
            <Button variant="secondary" size="sm" disabled={busy !== '' || job.state === 'running'} onclick={() => act(job, job.enabled ? 'pause' : 'resume')}>{job.enabled ? 'Pause' : 'Resume'}</Button>
            <Button variant="primary" size="sm" disabled={busy !== '' || job.state === 'running'} onclick={() => act(job, 'run')}>{job.state === 'running' ? 'Running…' : 'Run now'}</Button>
          </div>
          <section class="recent">
            <button type="button" class="disclosure" aria-expanded={!!expanded[job.key]} onclick={() => toggleRuns(job)}>
              <span>Recent runs</span><span aria-hidden="true">{expanded[job.key] ? '−' : '+'}</span>
            </button>
            {#if expanded[job.key]}
              {#if runs[job.key]?.length}
                <ul>{#each runs[job.key] as run (run.id)}<li><span><StatusPill status={jobStatusLabel(run.outcome)} tone={jobStateTone(run.outcome)} /> {displayDate(run.started_at)} · {run.trigger}</span>{#if run.cost_usd != null}<span>{displayCost(run.cost_usd)}</span>{/if}{#if run.error}<p class="run-error">{run.error}</p>{/if}</li>{/each}</ul>
              {:else}<p class="muted">No recent runs.</p>{/if}
            {/if}
          </section>
        </article>
      </Card>
    {/each}
  {/if}
</div>

<style>
  .page{display:grid;gap:var(--space-4);min-width:0}
  .job{display:grid;gap:var(--space-3);min-width:0}
  .heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2)}
  h2{margin:0;color:var(--text-strong);font-size:var(--font-size-md);overflow-wrap:anywhere}
  .details{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:var(--space-2);margin:0}
  .details div{min-width:0}
  dt{color:var(--text-muted);font-size:var(--font-size-xs)}
  dd{margin:var(--space-1) 0 0;color:var(--text-body);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .usage,.actions{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}
  .usage{color:var(--text-secondary);font-size:var(--font-size-sm)}
  .budget-field{display:grid;grid-template-columns:auto auto;align-items:center;gap:var(--space-1) var(--space-2);color:var(--text-body)}
  .budget-input{display:flex;align-items:center;gap:var(--space-2);color:var(--text-secondary);font-size:var(--font-size-xs)}
  .budget-field input{min-height:var(--control-h);padding:0 var(--space-2);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);font-family:inherit;font-size:var(--font-size-sm)}
  .budget-field small{grid-column:1/-1;color:var(--text-muted);font-size:var(--font-size-xs)}
  details{color:var(--text-secondary);font-size:var(--font-size-sm)}details summary{cursor:pointer}.job-details{margin-top:var(--space-2);color:var(--text-secondary);font-size:var(--font-size-sm)}
  .actions{padding-top:var(--space-1)}
  .recent{border-top:var(--line) solid var(--border-subtle)}
  .disclosure{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:var(--control-h);padding:0;border:0;background:transparent;color:var(--text-strong);font-family:inherit;font-size:inherit;font-weight:650;text-align:left;cursor:pointer}
  ul{display:grid;gap:var(--space-2);list-style:none;margin:0;padding:0}
  li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--space-2);min-width:0;font-size:var(--font-size-sm);overflow-wrap:anywhere}
  li p{grid-column:1/-1}
  .muted{margin:0;color:var(--text-muted);font-size:var(--font-size-sm)}
  .error,.run-error{margin:0;color:var(--status-blocked-fg);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .error{display:flex;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2);padding:var(--space-3);border-radius:var(--radius-control);background:var(--status-blocked-bg)}
  .error button{border:0;background:transparent;color:inherit;text-decoration:underline;cursor:pointer}
</style>
