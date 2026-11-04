<script lang="ts">
  import { getBotAudit, type BotAuditRow } from './botApi';
  import ActorBadge from './ActorBadge.svelte';
  import { formatDateTime } from './ui/date';
  import { Button, Dialog } from './ui';

  let { open = $bindable(false) }: { open?: boolean } = $props();
  let rows = $state<BotAuditRow[]>([]);
  let error = $state('');
  let loading = $state(false);
  let more = $state(true);
  let loaded = false;

  async function load(before?: number) {
    loading = true;
    error = '';
    try {
      const page = await getBotAudit(before);
      loaded = true;
      rows = before === undefined ? page : [...rows, ...page];
      more = page.length === 25;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Could not load bot audit.';
    } finally { loading = false; }
  }

  $effect(() => { if (open && !loaded) void load(); });
</script>

<Dialog bind:open title="Bot audit" description="Recent manager bot actions, newest first.">
  <div class="sheet">
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if rows.length === 0 && loading}<p class="muted">Loading audit…</p>
    {:else if rows.length === 0}<p class="muted">No audit actions yet.</p>
    {:else}
      <ol>
        {#each rows as row (row.id)}
          <li>
            <div class="line"><ActorBadge actor={row.actor} /><strong>{row.action}</strong><span>{row.status}</span></div>
            {#if row.reason}<p>{row.reason}</p>{/if}
            {#if row.agent_id}<a href={`/thread/${encodeURIComponent(row.agent_id)}`}>{row.agent_id}</a>
            {:else if row.plan_id}<a href={`/plans/${encodeURIComponent(row.plan_id)}`}>{row.plan_id}</a>{/if}
            <time datetime={row.ts}>{formatDateTime(row.ts)}</time>
          </li>
        {/each}
      </ol>
    {/if}
    {#if more && rows.length}<Button variant="secondary" disabled={loading} onclick={() => load(rows.at(-1)!.id)}>{loading ? 'Loading…' : 'Load more'}</Button>{/if}
  </div>
</Dialog>

<style>
  .sheet{display:grid;gap:var(--space-3);min-width:0;max-height:60dvh;overflow:auto}.muted,.error{margin:0;color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}.error{color:var(--text-danger)}ol{display:grid;gap:var(--space-2);margin:0;padding:0;list-style:none}li{display:grid;gap:var(--space-1);min-width:0;padding:var(--space-2) 0;border-bottom:var(--line) solid var(--border-subtle);font-size:var(--font-size-sm);overflow-wrap:anywhere}.line{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}li p{margin:0;color:var(--text-muted)}li a{min-height:var(--control-h);display:inline-flex;align-items:center;overflow-wrap:anywhere}time{color:var(--text-muted);font-size:var(--font-size-xs)}
</style>
