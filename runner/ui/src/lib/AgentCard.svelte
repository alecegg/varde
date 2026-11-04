<script lang="ts">
  import { Badge, Button, Card, OverflowMenu, StatusMarker } from './ui';
  import type { Agent } from './agentsApi';
  import { oneLine } from './agentRow';
  import ActorBadge from './ActorBadge.svelte';

  let { agent, busy = '', archived = false, onaction }: {
    agent: Agent;
    busy?: string;
    archived?: boolean;
    onaction: (agent: Agent, action: string) => void;
  } = $props();

  let expanded = $state(false);
  const can = (action: string) => action === 'prompt' || action === 'stop' || action === 'archive' || !!agent.capabilities[action];
  const row = $derived(oneLine(agent));
  const menuItems = $derived([
    ...(!archived && can('stop') ? [{ label: 'Stop', disabled: busy !== '', onclick: () => onaction(agent, 'stop') }] : []),
    ...(!archived && can('archive') ? [{ label: 'Archive', disabled: busy !== '', onclick: () => onaction(agent, 'archive') }] : []),
  ]);
</script>

<Card>
  <article class="agent">
    <div class="summary-row">
      <button class="summary" type="button" aria-expanded={expanded} onclick={() => expanded = !expanded}>
        <strong class="title">{row.title}</strong>
        <span class="short-id">{row.shortId}</span>
        <Badge tone={row.state.tone}>{row.state.label}</Badge>
      </button>
      {#if menuItems.length}<OverflowMenu label="Agent actions" items={menuItems} />{/if}
    </div>
    {#if expanded}
      <div class="details">
        <div class="heading">
          <h2>{row.title}</h2>
          <StatusMarker status={row.state.tone} label={`${row.state.icon} ${row.state.label}`} />
          <ActorBadge actor={agent.root_launched_by ?? agent.launched_by} />
        </div>
        <dl>
          <div><dt>Agent id</dt><dd>{agent.agent_id}</dd></div>
          <div><dt>Harness</dt><dd>{agent.harness}</dd></div>
          <div><dt>Role</dt><dd>{agent.role ?? 'Not assigned'}</dd></div>
          <div><dt>Workspace</dt><dd>{agent.workspace ?? 'Not assigned'}</dd></div>
        </dl>
        {#if agent.role}<a href="/roles">Configuration</a>{/if}
        <div class="actions">
          {#if !archived && can('prompt')}<Button size="sm" variant="secondary" disabled={busy !== ''} onclick={() => onaction(agent, 'prompt')}>Prompt</Button>{/if}
          {#if !archived && can('interrupt')}<Button size="sm" variant="secondary" disabled={busy !== ''} onclick={() => onaction(agent, 'interrupt')}>Interrupt</Button>{/if}
          {#if !archived && can('resume')}<Button size="sm" variant="secondary" disabled={busy !== ''} onclick={() => onaction(agent, 'resume')}>Resume</Button>{/if}
        </div>
      </div>
    {/if}
  </article>
</Card>

<style>
  .agent{display:grid;gap:var(--space-3);min-width:0}.summary-row{display:flex;align-items:center;gap:var(--space-1);min-width:0}.summary{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2);flex:1;min-width:0;min-height:var(--control-h);padding:0;border:0;background:transparent;color:var(--text-body);font:inherit;text-align:left;cursor:pointer}.summary>*{min-width:0}.title{flex:1 1 12ch;overflow-wrap:anywhere;color:var(--text-strong)}.short-id{color:var(--text-muted);font-size:var(--font-size-sm);font-variant-numeric:tabular-nums}.details{display:grid;gap:var(--space-3);min-width:0}.heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2)}h2{margin:0;color:var(--text-strong);font-size:var(--font-size-md);overflow-wrap:anywhere}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:var(--space-2);margin:0}dl div{min-width:0}dt{color:var(--text-muted);font-size:var(--font-size-xs)}dd{margin:var(--space-1) 0 0;color:var(--text-body);font-size:var(--font-size-sm);overflow-wrap:anywhere}.actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}
</style>
