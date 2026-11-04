<script lang="ts">
  import { onMount } from 'svelte';
  import { Card } from '../ui';
  import ThreadPanel from './ThreadPanel.svelte';
  import { loadThreads, onSnapshot, planOf, type ThreadMail } from './thread';

  let { planId, onneedsinput = () => {} }: { planId: string; onneedsinput?: (needsInput: boolean) => void } = $props();
  let mail = $state<ThreadMail[]>([]), error = $state(''), loading = $state(true);
  async function load() {
    try {
      const allThreads = await loadThreads();
      const threads = allThreads.filter(({ thread }) => planOf(thread) === planId)
        .sort((a, b) => Date.parse(b.thread.last_ts) - Date.parse(a.thread.last_ts));
      mail = threads;
      onneedsinput(threads.some(({ thread }) => thread.open_count > 0));
      error = '';
    } catch (e) { error = e instanceof Error ? e.message : 'Could not load plan mail'; }
    finally { loading = false; }
  }
  onMount(() => {
    const stopSnapshot = onSnapshot(['mailbox'], load);
    load();
    return stopSnapshot;
  });
</script>
<section id="mail" aria-label="Plan mail">
  <Card title="Mail">
    {#if error}<p class="error" role="alert">{error}</p>
    {:else if loading}<p>Loading mail…</p>
    {:else if mail.length}
      <div class="threads">{#each mail as item (item.thread.thread_id)}
        <section class="thread-section">
          {#if mail.length > 1}<h3 class="thread-label">{item.thread.sender || item.thread.title || 'Thread'}</h3>{/if}
        <ThreadPanel {...item} placement="inline" messageOrder="newest-first" showTitle={false} onupdated={load} />
        </section>
      {/each}</div>
    {:else}<p>No mail for this plan.</p>{/if}
  </Card>
</section>
<style>
  section{min-width:0;scroll-margin-top:var(--space-4)}
  .threads{display:grid;gap:var(--space-4);min-width:0}
  .threads :global(.thread){padding-bottom:calc(var(--tab-bar-h,0px) + var(--space-3))}
  .thread-section + .thread-section{padding-top:var(--space-3);border-top:var(--line) solid var(--border-subtle)}
  .thread-label{margin:0 0 var(--space-2);color:var(--text-muted);font-size:var(--font-size-xs);font-weight:650;overflow-wrap:anywhere}
  .error{margin:0;color:var(--status-blocked-fg);overflow-wrap:anywhere}
</style>
