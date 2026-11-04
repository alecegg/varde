<script lang="ts">
  import { Button, Card, DisclosureRow, StatusPill } from './ui';
  import AgentWatch from './AgentWatch.svelte';
  import { defaultVisibleAgents } from './agents';
  import { ageLabel, display, statusState, type Row } from './plans';
  let { agents }: { agents: Row[] } = $props();
  let showAll = $state(false);
  let outerOpen = $state(false);
  let openAgentId = $state<string | null>(null);
  let visible = $derived(showAll ? agents : defaultVisibleAgents(agents));
</script>
<details class="other" bind:open={outerOpen}><summary>Other agents · {agents.length}</summary><Card>
  <ul class="agent-list">{#each visible as agent}{@const agentId = typeof agent.id === 'string' ? agent.id : ''}{@const agentName = display(agent.title ?? agent.id)}{@const state = statusState(agent.status)}<li><strong>{agentName}</strong><span>{ageLabel(agent.lastActivity ?? agent.lastActivityAt ?? agent.last_activity ?? agent.updatedAt)}</span><StatusPill status={state === 'done' ? 'done' : state} tone={state === 'running' ? 'running' : state === 'blocked' ? 'blocked' : state === 'needs-input' ? 'needs-input' : state === 'done' ? 'success' : 'idle'} />
    {#if agentId}<DisclosureRow title="Watch" ariaLabel={`Watch ${agentName}`} id={`other-agent-watch-${encodeURIComponent(agentId)}`} open={openAgentId === agentId} onToggle={(open) => (openAgentId = open ? agentId : null)}>{#if outerOpen && openAgentId === agentId}<AgentWatch {agentId} />{/if}</DisclosureRow>{/if}
  </li>{/each}</ul>
  {#if agents.length > visible.length || (showAll && agents.length)}<Button variant="secondary" onclick={() => (showAll = !showAll)} aria-expanded={showAll}>{showAll ? 'Show fewer' : `Show all ${agents.length}`}</Button>{/if}
  {#if !agents.length}<p>No other Paseo agents listed.</p>{/if}
</Card></details>
<style>
  .other summary{display:flex;align-items:center;min-height:var(--control-h);cursor:pointer;color:var(--text-strong);font-weight:650}
  .agent-list{list-style:none;padding:0;margin:0}
  .agent-list li{display:flex;align-items:center;gap:var(--space-2);min-height:var(--row-min-h);border-top:var(--line) solid var(--border-subtle);flex-wrap:wrap}
  .agent-list strong{flex:1;min-width:0;overflow-wrap:anywhere}
  .agent-list :global(.disclosure-row){flex-basis:100%}
</style>
