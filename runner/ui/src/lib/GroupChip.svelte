<script lang="ts">
  let { name }: { name: string } = $props();
</script>

{#if name}<span class="group-chip">{name}</span>{/if}

<style>
  .group-chip {
    flex: none;
    max-width: 100%;
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    color: var(--text-muted);
    font-size: var(--font-size-xs);
    line-height: 1.6;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
