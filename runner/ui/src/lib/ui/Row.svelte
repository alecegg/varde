<script lang="ts">
  import type { Snippet } from 'svelte';
  // Link row: title, optional meta line, optional chips; trailing holds actions.
  let { href, title, meta, chips, trailing }: { href?: string; title: string; meta?: string; chips?: Snippet; trailing?: Snippet } = $props();
</script>
<div class="row">
  <svelte:element this={href ? 'a' : 'div'} class="copy" {href}>
    <span class="title">{title}</span>
    {#if meta}<span class="meta">{meta}</span>{/if}
    {#if chips}<span class="chips">{@render chips()}</span>{/if}
  </svelte:element>
  {#if trailing}<div class="trailing">{@render trailing()}</div>{/if}
</div>
<style>
  .row{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-3) 0;border-top:var(--line) solid var(--border-subtle)}
  .row:first-child{border-top:0}
  .copy{display:grid;gap:var(--space-1);flex:1;min-width:0;min-height:var(--row-min-h);align-content:center;text-decoration:none;color:inherit}
  .title{color:var(--text-strong);font-weight:650;line-height:1.35;overflow-wrap:anywhere}
  .meta{color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .chips{display:flex;flex-wrap:wrap;gap:var(--space-1)}
  .trailing{display:flex;flex:none;gap:var(--space-1)}
</style>
