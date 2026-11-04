<script lang="ts">
  import { onMount } from 'svelte';
  import NeedsYou from '../NeedsYou.svelte';
  import MergeApproval from '../MergeApproval.svelte';
  import { api } from '../queue';
  import { isMergeReady, type ApprovalPlan } from '../mergeApproval';
  import { refreshWhenVisible } from '../refresh';
  import { onSnapshot } from '../mail/thread';

  let { onsettled = () => {} }: { onsettled?: () => void } = $props();
  let plans = $state<ApprovalPlan[]>([]);
  async function loadPlans() {
    try { const data = await api<{ plans?: ApprovalPlan[] }>('/api/orchestrators'); plans = (data.plans ?? []).filter(isMergeReady); }
    catch { plans = []; }
  }
  onMount(() => {
    loadPlans();
    const stopSnapshot = onSnapshot(['orchestrators'], loadPlans);
    const stopVisibleRefresh = refreshWhenVisible(loadPlans);
    return () => { stopVisibleRefresh(); stopSnapshot(); };
  });
</script>

{#if plans.length}<section class="merge-needs" aria-label="Merge approvals"><h2>Merge approvals</h2>{#each plans as plan (plan.id)}<article><strong>{plan.id}</strong><MergeApproval {plan} onapproved={() => plans = plans.filter((item) => item.id !== plan.id)} /></article>{/each}</section>{/if}
<NeedsYou limit={Number.MAX_SAFE_INTEGER} {onsettled} />
<style>.merge-needs{display:grid;gap:var(--space-2);min-width:0}.merge-needs h2{margin:0;color:var(--text-strong);font-size:var(--font-size-md)}.merge-needs article{display:grid;gap:var(--space-2);min-width:0;padding:var(--space-3);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);overflow-wrap:anywhere}</style>
