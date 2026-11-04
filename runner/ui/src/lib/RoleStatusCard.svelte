<script lang="ts">
  import { onMount } from 'svelte';
  import { statusCardModel } from './roleStatus';

  let { role }: { role: string } = $props();
  let card = $state<{ text: string; href: string } | null>(null);

  onMount(() => {
    let active = true;
    fetch(`/api/queue/roles/${encodeURIComponent(role)}`, { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Role status unavailable');
        return response.json();
      })
      .then((data) => {
        if (!active || !data?.summary) return;
        card = statusCardModel(data.summary);
      })
      .catch(() => {});
    return () => { active = false; };
  });
</script>

{#if card}
  <a class="card" href={card.href} aria-label={card.text}>
    <span class="status">{card.text}</span>
    <span class="arrow" aria-hidden="true">›</span>
  </a>
{/if}

<style>
  .card{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);min-width:0;min-height:48px;padding:var(--space-2) var(--space-3);border:var(--line) solid var(--cf-line);border-radius:var(--radius-control);background:var(--cf-soft);color:var(--cf-text);font-size:var(--font-size-sm);font-weight:700;text-decoration:none}
  :global(:root[data-theme=dark]) .card{background:var(--cf-panel)}
  .card:hover{border-color:var(--border);background:var(--surface-2)}
  .status{min-width:0;color:var(--cf-text);font-size:var(--font-size-sm);font-weight:700;overflow-wrap:anywhere}
  .arrow{flex:none;color:var(--cf-text);font-size:16px;font-weight:700}
</style>
