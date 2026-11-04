<script lang="ts">
  let { count, loading = false, error = false, active = false, href = '/chat/needs' }: { count: number; loading?: boolean; error?: boolean; active?: boolean; href?: string } = $props();
  let caughtUp = $derived(!loading && !error && count === 0);
</script>

<a class="needs-action" class:caught-up={caughtUp} class:active {href} aria-label={loading ? 'Needs action loading' : error ? 'Needs action status unavailable' : `Needs action, ${count} pending`}>
  <span class="mark-wrap"><span class="mark" aria-hidden="true">{#if loading}…{:else if error}?{:else if count > 0}!{:else}<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg>{/if}</span>
    {#if !loading && !error && count > 0}<span class="badge" aria-hidden="true">{count}</span>{/if}
  </span>
  <span class="label">Needs action</span>
</a>

<style>
  .needs-action{position:relative;display:flex;flex-direction:column;align-items:center;gap:var(--space-2);width:calc(var(--control-h) + var(--space-6));color:var(--cf-muted);font-size:var(--font-size-xs);text-decoration:none}.mark-wrap{position:relative;width:var(--control-h);height:var(--control-h)}.mark{box-sizing:border-box;display:grid;place-items:center;width:100%;height:100%;border:var(--line) solid var(--cf-primary);border-radius:var(--radius-pill);background:var(--cf-primary);color:var(--cf-primary-ink);font-size:var(--font-size-lg);font-weight:750}.caught-up .mark{border-color:var(--cf-line);background:var(--cf-soft);color:var(--cf-muted)}.mark svg{width:var(--icon-size);height:var(--icon-size);fill:none;stroke:currentColor;stroke-width:var(--line);stroke-linecap:round;stroke-linejoin:round}.badge{position:absolute;top:0;right:0;display:grid;min-width:var(--space-4);height:var(--space-4);padding:0 var(--space-1);place-items:center;border:var(--line) solid var(--cf-bg);border-radius:var(--radius-pill);background:var(--cf-badge);color:var(--cf-badge-ink);font-size:var(--font-size-xs);font-weight:800}.label{max-width:calc(var(--control-h) + var(--space-6));line-height:1.15;text-align:center}
</style>
