<script lang="ts">
  import Dialog from './Dialog.svelte';
  import Badge from './Badge.svelte';
  import Markdown from './Markdown.svelte';
  type Item = { kind: 'shot' | 'note' | 'diff' | 'tests' | 'review' | 'conflicts'; caption?: string; text?: string };
  const ROW_ORDER = ['tests', 'review', 'diff', 'conflicts'];
  let { items, urlFor }: { items: Item[]; urlFor: (index: number) => string } = $props();
  // Server index is the position in the original list; diff stats lead the display.
  const entries = $derived(items.map((item, index) => ({ item, url: urlFor(index) })).sort((a, b) => Number(b.item.kind === 'diff') - Number(a.item.kind === 'diff')));
  // Summary kinds (Tests, Review, Conflicts) turn the block into labelled rows; Diff joins them when they exist.
  const labelled = $derived(entries.some((entry) => ['tests', 'review', 'conflicts'].includes(entry.item.kind)));
  const isRow = (item: Item) => labelled && ROW_ORDER.includes(item.kind);
  const rows = $derived(entries.filter((entry) => isRow(entry.item)).sort((a, b) => ROW_ORDER.indexOf(a.item.kind) - ROW_ORDER.indexOf(b.item.kind)));
  const rest = $derived(entries.filter((entry) => !isRow(entry.item)));
  const label = (kind: string) => kind[0].toUpperCase() + kind.slice(1);
  const summary = (item: Item) => (item.text ?? '').trim().split('\n').filter(Boolean).at(-1) ?? '';
  function tone(item: Item) {
    const text = summary(item);
    if (item.kind === 'diff') return 'idle';
    if (/fail|error/i.test(text) || (item.kind === 'conflicts' && !/^(none|no)\b/i.test(text))) return 'blocked';
    return 'success';
  }
  async function loadNote(url: string) { const response = await fetch(url); if (!response.ok) throw new Error(`Note unavailable (${response.status})`); return response.text(); }
</script>
{#snippet shotTrigger(props: Record<string, unknown>, caption: string, url: string)}<button type="button" class="thumb" aria-label={`Open screenshot: ${caption}`} {...props}><img src={url} alt="" loading="lazy" /></button>{/snippet}
<div class="evidence">
  {#if rows.length}
    <div class="rows">
      {#each rows as { item }}
        <div class="ev-row"><span class="ev-label">{label(item.kind)}</span><Badge tone={tone(item)}>{summary(item)}</Badge></div>
        {#if item.kind === 'diff' && (item.text ?? '').trim().includes('\n')}<details class="diff-stat"><summary>Diff stat</summary><pre class="diff">{item.text}</pre></details>{/if}
      {/each}
    </div>
  {/if}
  {#each rest as { item, url }}
    <figure class="entry">
      {#if item.kind === 'diff'}<pre class="diff">{item.text}</pre>
      {:else if item.kind === 'shot'}<Dialog title={item.caption || 'Screenshot'}>{#snippet trigger(props)}{@render shotTrigger(props, item.caption || 'Screenshot', url)}{/snippet}<img class="full" src={url} alt={item.caption || 'Screenshot'} /></Dialog>
      {:else if item.text}<Markdown text={item.text} />
      {:else}{#await loadNote(url)}<small class="status">Loading note…</small>{:then text}<Markdown {text} />{:catch error}<small class="status" role="alert">{error.message}</small>{/await}{/if}
      {#if item.caption}<figcaption>{item.caption}</figcaption>{/if}
    </figure>
  {/each}
</div>
<style>
  .evidence{display:grid;gap:var(--space-3);min-width:0}
  .rows{display:grid}
  .ev-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-2) 0;border-top:var(--line) solid var(--border-subtle)}
  .ev-row:first-child{border-top:0}
  .ev-label{color:var(--text-strong);font-weight:650}
  .diff-stat summary{min-height:var(--control-h);display:flex;align-items:center;color:var(--text-muted);font-size:var(--font-size-xs);cursor:pointer}
  .entry{margin:0;min-width:0;display:grid;gap:var(--space-1)}
  figcaption,.status{color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .diff{margin:0;padding:var(--space-3);overflow-x:auto;max-width:100%;border:var(--line) solid var(--border-subtle);border-radius:var(--radius-control);background:var(--surface-code);color:var(--code);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--font-size-xs);line-height:1.5}
  .thumb{display:block;width:100%;min-height:var(--control-h);padding:0;overflow:hidden;border:var(--line) solid var(--border);border-radius:var(--radius-control);background:var(--surface-2);touch-action:manipulation;cursor:zoom-in}
  .thumb img{display:block;width:100%;max-height:10rem;object-fit:cover;object-position:top}
  .full{display:block;max-width:100%;height:auto;margin-bottom:var(--space-3)}
</style>
