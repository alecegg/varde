<script lang="ts">
  import { onMount } from 'svelte';
  import { listAgents, openAgentWriter, respondAgent, type Agent } from '../agentsApi';
  import { refreshWhenVisible } from '../refresh';
  import { approvalsForThread, answerForRequest, recordApprovalAnswer } from './inlineApproval';
  import type { ChatMessage } from './chatState';

  let { threadKey, messages = [] }: { threadKey: string; messages?: ChatMessage[] } = $props();
  let agents = $state<Agent[]>([]);
  let answering = $state('');
  let error = $state('');
  let answered = $state<Record<string, 'approved' | 'denied'>>({});
  let collapsing = $state(new Set<string>());
  let approvals = $derived(approvalsForThread(threadKey, agents));

  async function refresh() {
    try { agents = await listAgents(); error = ''; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not refresh approvals.'; }
  }

  async function answer(agent: Agent, requestId: string, decision: string) {
    const key = `${agent.agent_id}:${requestId}`;
    answering = key;
    error = '';
    let writer: Awaited<ReturnType<typeof openAgentWriter>> | undefined;
    try {
      writer = await openAgentWriter(agent.agent_id, () => {});
      await respondAgent(agent.agent_id, writer, requestId, decision);
      answered = recordApprovalAnswer(answered, key, decision);
      window.setTimeout(() => {
        collapsing = new Set([...collapsing, key]);
        window.setTimeout(() => { void refresh(); }, 300);
      }, 900);
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not answer this request.'; }
    finally { writer?.close(); answering = ''; }
  }

  onMount(() => {
    void refresh();
    return refreshWhenVisible(() => { void refresh(); });
  });
</script>

{#if approvals.length}<section class="approvals" aria-label="Pending approvals">
  {#each approvals as { agent, request } (`${agent.agent_id}:${request.request_id}`)}
    {@const key = `${agent.agent_id}:${request.request_id}`}
    {@const state = answered[key] ?? answerForRequest(messages, request.request_id)}
    <article class="approval bubble theirs" class:resolved={Boolean(state)} class:collapsing={collapsing.has(key)} data-testid="inline-approval" data-answer-card={key} data-answer={state ?? ''}>
      <strong class="approval-title">Approval request</strong>
      <span class="summary">{request.summary}</span>
      {#if state}<div class="meta"><span class="state" class:denied={state === 'denied'}>{state === 'approved' ? 'Approved' : 'Denied'}</span></div>
      {:else}<div class="actions">
        <button class="btn primary" type="button" data-answer="allow" disabled={answering !== ''} onclick={() => answer(agent, request.request_id, 'allow')}>Allow</button>
        <button class="btn danger" type="button" data-answer="deny" disabled={answering !== ''} onclick={() => answer(agent, request.request_id, 'deny')}>Deny</button>
      </div>{/if}
    </article>
  {/each}
</section>{/if}
{#if error}<p class="error" role="status">{error}</p>{/if}

<style>
  .approvals{display:contents}
  .approval{align-self:flex-start;display:flex;flex-direction:column;align-items:flex-start;max-width:92%;padding:12px 16px;border:0;border-radius:20px 20px 20px 6px;background:var(--cf-soft);color:var(--cf-text);font-size:17px;line-height:1.4;overflow:hidden;max-height:320px;transition:max-height 300ms ease,opacity 300ms ease,padding 300ms ease,margin 300ms ease,border-width 300ms ease;animation:bubble-in 160ms ease both}
  .approval.resolved{background:var(--cf-soft)}.approval.collapsing{max-height:0;opacity:0;padding-block:0;margin-block:0;border-width:0}
  .approval-title{margin-bottom:8px;overflow-wrap:anywhere;font-weight:700}.summary{overflow-wrap:anywhere}.actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}.btn{min-height:48px;padding:0 18px;border:0;border-radius:999px;background:var(--cf-soft);color:var(--cf-text);font-size:15px;font-weight:650;cursor:pointer}.btn.primary{background:var(--cf-primary);color:var(--cf-primary-ink)}.btn.danger{color:var(--cf-bad)}button:disabled{opacity:.55;cursor:default}.state{display:inline-block;padding:5px 11px;border-radius:999px;background:var(--cf-goodbg);color:var(--cf-good);font-weight:700}.state.denied{background:var(--cf-badbg);color:var(--cf-bad)}
  @media(prefers-reduced-motion:reduce){.approval{transition:none}}
</style>
