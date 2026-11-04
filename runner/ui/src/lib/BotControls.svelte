<script lang="ts">
  import { onMount } from 'svelte';
  import { controlBot, getBotState, percentage, type BotSnapshot } from './botApi';
  import AuditSheet from './AuditSheet.svelte';
  import { Button, Dialog, OverflowMenu } from './ui';

  let { snapshot = $bindable<BotSnapshot | null>(null), contextPct = null }: { snapshot?: BotSnapshot | null; contextPct?: number | null } = $props();
  let busy = $state(false);
  let error = $state('');
  let confirmKill = $state(false);
  let auditOpen = $state(false);
  let context = $derived(percentage(snapshot?.tokens_today ?? 0, snapshot?.daily_token_budget ?? 0));

  async function refresh() {
    try { snapshot = await getBotState(); error = ''; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load bot status.'; }
  }

  async function act(action: 'pause' | 'resume' | 'kill') {
    busy = true;
    error = '';
    try { snapshot = await controlBot(action); confirmKill = false; }
    catch (cause) { error = cause instanceof Error ? cause.message : `Could not ${action} the bot.`; }
    finally { busy = false; }
  }

  onMount(() => { void refresh(); });
</script>

<section class="controls" aria-label="Manager bot controls">
  <div class="status-row">
    {#if snapshot}<span class="meter">Agents {snapshot.agents}/{snapshot.max_concurrent_agents}</span><span class="meter">Budget {context ?? 0}%</span>{#if contextPct !== null}<span class="meter">Context {contextPct}%</span>{/if}{/if}
    {#if snapshot?.state === 'running'}<Button size="sm" variant="secondary" disabled={busy} onclick={() => act('pause')}>Pause</Button>
    {:else if snapshot?.state === 'paused'}<Button size="sm" variant="secondary" disabled={busy} onclick={() => act('resume')}>Resume</Button>{/if}
    <OverflowMenu items={[{ label: 'View audit', onclick: () => auditOpen = true }, { label: 'Kill bot…', disabled: !snapshot || snapshot.state === 'killed' || busy, onclick: () => confirmKill = true }]} />
  </div>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<Dialog bind:open={confirmKill} title="Kill the manager bot?" description="This stops the bot and its managed agents. A killed bot cannot be resumed.">
  <div class="actions"><Button variant="danger" disabled={busy} onclick={() => act('kill')}>Kill bot</Button><Button variant="secondary" onclick={() => confirmKill = false}>Cancel</Button></div>
</Dialog>
<AuditSheet bind:open={auditOpen} />

<style>
  .controls{display:grid;gap:var(--space-1);min-width:0;padding-block:var(--space-2);border-bottom:var(--line) solid var(--border-subtle)}.status-row{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);min-width:0;padding-inline:16px}.meter{color:var(--text-muted);font-size:var(--font-size-xs)}.error{margin:0;color:var(--text-danger);font-size:var(--font-size-xs);overflow-wrap:anywhere}.actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:var(--space-2)}
</style>
