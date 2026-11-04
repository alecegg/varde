<script lang="ts">
  import { Badge, Card, StatusPill, safeLabel } from './ui';
  import { display, infraProblems, type Row } from './plans';
  let { infrastructure }: { infrastructure: Row[] } = $props();
  const problems = $derived(infraProblems(infrastructure));
  function agentStatus(value: string): 'running' | 'alive' | 'error' | 'stale' | 'missing' | 'unknown' | 'idle' {
    if (value === 'running' || value === 'alive' || value === 'error' || value === 'stale' || value === 'missing' || value === 'unknown') return value;
    return 'idle';
  }
</script>
<Card title={problems.length ? `Infrastructure · ${problems.length} need attention` : 'Infrastructure'}>
  {#if !problems.length}<p class="ok">{infrastructure.length ? 'All good.' : 'No infrastructure agents registered.'}</p>{/if}
  {#if problems.length}<p class="next-step">Review runner settings and check that the listed agents are available. <a href="/settings/runner">Open runner settings</a>.</p>{/if}
  <ul class="agent-list">{#each problems as agent}{@const name = safeLabel(agent.address, '')}<li>{#if name}<strong>{name}</strong>{/if}<StatusPill status={agentStatus(agent.status)} tone={agent.status === 'running' || agent.status === 'alive' ? 'running' : ['error', 'stale', 'missing', 'unknown'].includes(agent.status) ? 'danger' : 'idle'} /></li>{/each}</ul>
</Card>
<style>
  .ok{margin:0;color:var(--text-muted)}
  .next-step{margin:0 0 var(--space-2);color:var(--text-muted);font-size:var(--font-size-sm)}.next-step a{color:var(--text-link)}
  .agent-list{list-style:none;padding:0;margin:0}
  .agent-list li{display:flex;align-items:center;gap:var(--space-2);min-height:var(--row-min-h);border-top:var(--line) solid var(--border-subtle);flex-wrap:wrap}
  .agent-list strong{flex:1;min-width:0;overflow-wrap:anywhere}
</style>
