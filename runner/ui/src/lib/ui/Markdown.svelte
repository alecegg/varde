<script lang="ts">
  import { renderMarkdown } from '../markdown';
  let { text }: { text: string } = $props();
  // renderMarkdown escapes all input, so the HTML holds only the tags it emits.
  const html = $derived(renderMarkdown(text));
</script>
<div class="markdown">{@html html}</div>
<style>
  .markdown{min-width:0;color:var(--text-body);font-size:var(--font-size-sm);line-height:1.55;overflow-wrap:anywhere}
  .markdown :global(:first-child){margin-top:0}.markdown :global(:last-child){margin-bottom:0}
  .markdown :global(h2),.markdown :global(h3),.markdown :global(h4),.markdown :global(h5),.markdown :global(h6){margin:var(--space-5) 0 var(--space-2);color:var(--text-strong);line-height:1.3}
  .markdown :global(h2){font-size:var(--font-size-md)}.markdown :global(h3),.markdown :global(h4),.markdown :global(h5),.markdown :global(h6){font-size:var(--font-size-sm)}
  .markdown :global(p),.markdown :global(ul),.markdown :global(ol),.markdown :global(blockquote),.markdown :global(pre){margin:0 0 var(--space-3)}
  .markdown :global(ul),.markdown :global(ol){padding-left:var(--space-5);display:grid;gap:var(--space-1)}
  .markdown :global(.task-list-item){list-style:none}
  .markdown :global(.task-list-item input){width:1rem;height:1rem;margin:0 var(--space-2) 0 0;vertical-align:-.15em}
  .markdown :global(a){color:var(--accent);min-height:0}
  .markdown :global(code){padding:0 var(--space-1);border-radius:var(--radius-control);background:var(--surface-code);color:var(--code);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--font-size-xs)}
  .markdown :global(pre){padding:var(--space-3);overflow-x:auto;border:var(--line) solid var(--border-subtle);border-radius:var(--radius-control);background:var(--surface-code)}
  .markdown :global(pre code){padding:0;background:transparent}
  .markdown :global(blockquote){margin-inline:0;padding:var(--space-2) var(--space-3);border-radius:var(--radius-control);background:var(--surface-inset);color:var(--text-secondary)}
  .markdown :global(hr){border:0;border-top:var(--line) solid var(--border-subtle);margin:var(--space-4) 0}
  .markdown :global(.table-scroll){overflow-x:auto;margin-bottom:var(--space-3)}
  .markdown :global(table){border-collapse:collapse;font-size:var(--font-size-xs)}
  .markdown :global(th),.markdown :global(td){padding:var(--space-1) var(--space-2);border:var(--line) solid var(--border-subtle);text-align:left;vertical-align:top}
</style>
