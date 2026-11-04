<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from './queue';
  import { refreshWhenVisible } from './refresh';
  import { onSnapshot } from './mail/thread';
  import { isMergeReady, approvalBody, validateNote, type ApprovalPlan } from './mergeApproval';
  import { Badge, Button, Dialog, Textarea } from './ui';
  import { formatDateTime } from './ui/date';
  let { plan, onapproved = () => {}, needsInput = false }: { plan: ApprovalPlan; onapproved?: () => void; needsInput?: boolean } = $props();
  let open = $state(false), note = $state(''), error = $state(''), busy = $state(false);
  let approval = $state<{ approved_by?: string; approved_at?: string; note?: string | null } | null>(null);
  const ready = $derived(isMergeReady(plan));
  async function loadApproval() {
    try { approval = (await api<{ approval: typeof approval }>(`/api/plans/${encodeURIComponent(plan.id)}/merge-approval`)).approval; }
    catch { approval = null; }
  }
  async function approve() {
    const validation = validateNote(note);
    if (validation) { error = validation; return; }
    busy = true; error = '';
    try {
      const result = await api<{ approval: typeof approval }>(`/api/plans/${encodeURIComponent(plan.id)}/merge-approval`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(approvalBody(note)) });
      approval = result.approval; open = false; onapproved();
    } catch (e) { error = e instanceof Error ? e.message : 'Could not approve merge'; }
    finally { busy = false; }
  }
  onMount(() => {
    loadApproval();
    const stopSnapshot = onSnapshot(['orchestrators'], loadApproval);
    const stopVisibleRefresh = refreshWhenVisible(loadApproval);
    return () => { stopVisibleRefresh(); stopSnapshot(); };
  });
</script>
{#if approval}<div class="approved"><Badge tone="success">Merge approved</Badge>{#if approval.approved_by}<p>By {approval.approved_by}</p>{/if}{#if approval.approved_at}<time>{formatDateTime(approval.approved_at)}</time>{/if}{#if approval.note}<p>{approval.note}</p>{/if}</div>
{:else if ready}<Dialog bind:open title="Approve merge?" description={`Record your approval for ${plan.id}.`}>
  {#snippet trigger(props)}<Button {...props} class="merge-approval-target" size="sm" variant="primary" disabled={needsInput}>Approve merge</Button>{/snippet}
  <div class="form"><Textarea label="Optional note" bind:value={note} maxlength={500} placeholder="Add a note for the merge record" /><small>{note.length}/500</small>{#if error}<p role="alert">{error}</p>{/if}</div>
  {#snippet actions()}<Button class="merge-approval-target" variant="secondary" disabled={busy} onclick={() => open = false}>Cancel</Button><Button class="merge-approval-target" variant="primary" disabled={busy || Boolean(validateNote(note))} onclick={approve}>{busy ? 'Approving…' : 'Confirm approval'}</Button>{/snippet}
</Dialog>{/if}
{#if needsInput && !approval}<p class="approval-hint">Answer the pending question above before approving the merge.</p>{/if}
<style>:global(.ui-button.merge-approval-target){min-height:var(--nav-item-h)}.approved{display:grid;gap:var(--space-1);min-width:0}.approved time,.approved p{margin:0;color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}.form{display:grid;gap:var(--space-1);min-width:0}.form small{justify-self:end;color:var(--text-muted)}.form p{margin:0;color:var(--status-blocked-fg);overflow-wrap:anywhere}</style>
