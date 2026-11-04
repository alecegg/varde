<script lang="ts">
  let { actor }: { actor: string | null | undefined } = $props();
  const label = $derived(actor === 'manager' || actor?.startsWith('bot:manager') ? 'Manager bot' : actor ?? '');
</script>

{#if label}<span class="actor-badge" aria-label={`Actor: ${label}`} title={actor}>{label}</span>{/if}

<style>
  .actor-badge{display:inline-flex;align-items:center;min-height:20px;padding:0 var(--space-2);border:var(--line) solid var(--border-subtle);border-radius:var(--radius-pill);background:var(--surface-inset);color:var(--text-muted);font-size:var(--font-size-xs);line-height:1.2;white-space:nowrap}
</style>
