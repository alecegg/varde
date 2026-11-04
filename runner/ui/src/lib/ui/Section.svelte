<script lang="ts">
  import type { Snippet } from 'svelte';
  // tone: attention stands out, quiet recedes; default is a plain group.
  const id = $props.id();
  let { title, count, tone = 'default', children }: { title: string; count?: number; tone?: 'default' | 'attention' | 'quiet'; children: Snippet } = $props();
</script>
<section class={`section ${tone}`} aria-labelledby={id}>
  <header><h2 {id}>{title}</h2>{#if count !== undefined}<span>{count}</span>{/if}</header>
  <div class="body">{@render children()}</div>
</section>
<style>
  .section{min-width:0;padding:var(--space-3) var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1)}
  header{display:flex;align-items:center;gap:var(--space-2);min-height:var(--control-h)}
  h2{margin:0;color:var(--text-strong);font-size:var(--font-size-md)}
  header span{color:var(--text-muted);font-size:var(--font-size-sm)}
  .attention{border-color:var(--status-needs-input-fg);background:var(--surface-accent)}
  .quiet{background:var(--surface-0);border-style:dashed}.quiet h2{color:var(--text-muted);font-size:var(--font-size-sm)}
</style>
