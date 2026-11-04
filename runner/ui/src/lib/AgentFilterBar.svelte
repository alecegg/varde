<script lang="ts">
  import { FilterChip, SearchInput } from './ui';
  import { stateCounts, type AgentFilter, type AgentFilterState } from './agentFilter';
  import type { Agent } from './agentsApi';

  let { agents, value = $bindable({ state: 'all', query: '' }), onchange }: {
    agents: Agent[];
    value?: AgentFilter;
    onchange?: (filter: AgentFilter) => void;
  } = $props();
  const states: { state: AgentFilterState; label: string }[] = [
    { state: 'all', label: 'All' }, { state: 'blocked', label: 'Blocked' },
    { state: 'running', label: 'Running' }, { state: 'idle', label: 'Idle' },
    { state: 'completed', label: 'Completed' }, { state: 'failed', label: 'Failed' },
  ];
  let counts = $derived(stateCounts(agents));

  function setFilter(next: AgentFilter) {
    value = next;
    onchange?.(next);
  }
</script>

<div class="filter-bar" aria-label="Filter agents">
  <SearchInput aria-label="Search agents" placeholder="Search agents" bind:value={value.query} />
  <div class="chips" aria-label="Agent state">
    {#each states as item (item.state)}
      <FilterChip active={value.state === item.state} onclick={() => setFilter({ ...value, state: item.state })}>{item.label} <span>{counts[item.state]}</span></FilterChip>
    {/each}
  </div>
</div>

<style>
  .filter-bar{display:grid;gap:var(--space-2);min-width:0}.chips{display:flex;gap:var(--space-2);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:thin;padding-block:2px}.chips :global(button){min-height:44px;flex:0 0 auto}.chips span{margin-left:var(--space-1);font-variant-numeric:tabular-nums}
</style>
