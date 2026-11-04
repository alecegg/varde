<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { slide } from 'svelte/transition';
  import { Button, Card } from './ui';
  import { loadThreads, normalizeThreadMail, onSnapshot, type ThreadMail } from './mail/thread';
  import { degradedSourceLabels } from './degradedSources';
  import { listAgents, openAgentWriter, respondAgent, type Agent } from './agentsApi';
  import { answerState } from './approvalCard';
  import { permissionTitle, senderName } from './chat/conversationRows';
  import { needsYouRows } from './chat/needsYouRows';
  import { mailboxItemAction, needsYouAnswerText, needsYouOptionLabel, needsYouRefreshFailureMessage } from './needsYouShort';
  import { cacheRead, cacheWrite } from './cache';
  import Skeleton from './ui/Skeleton.svelte';

  type MailDecision = {
    msg_id: string;
    kind?: string;
    type?: string;
    asked?: string;
    body?: string;
    title?: string;
    agent?: string;
    agent_title?: string;
    options?: Array<string | { label?: string; title?: string }>;
  };

  function mailDecision(value: Record<string, unknown>): MailDecision {
    return {
      msg_id: typeof value.msg_id === 'string' ? value.msg_id : '',
      kind: typeof value.kind === 'string' ? value.kind : undefined,
      type: typeof value.type === 'string' ? value.type : undefined,
      asked: typeof value.asked === 'string' ? value.asked : undefined,
      body: typeof value.body === 'string' ? value.body : undefined,
      title: typeof value.title === 'string' ? value.title : undefined,
      agent: typeof value.agent === 'string' ? value.agent : undefined,
      agent_title: typeof value.agent_title === 'string' ? value.agent_title : undefined,
      options: Array.isArray(value.options) ? value.options as MailDecision['options'] : undefined,
    };
  }

  let { limit = Number.MAX_SAFE_INTEGER, onsettled = () => {}, chat = false }: { limit?: number; onsettled?: () => void; chat?: boolean } = $props();
  let threads = $state<ThreadMail[]>([]), agents = $state<Agent[]>([]), error = $state(''), degraded = $state<string[]>([]), answering = $state(''), loading = $state(true);
  let replying = $state(new Set<string>());
  let mailboxSending = $state(''), mailboxConfirmation = $state('');
  let retrying = $state(false);
  let mailboxOptions = $state<Record<string, string>>({});
  let mailboxReplies = $state<Record<string, string>>({});
  let selectedItem = $derived(page?.url?.searchParams.get('item') ?? '');
  let resolvedRequestIds = $state(new Set<string>()), answered = $state<Record<string, string>>({});
  let other = $derived(threads.filter(({ thread }) => thread.open_count === 0));
  let degradedLabels = $derived(degradedSourceLabels(degraded));
  let rows = $derived(needsYouRows(threads, agents, resolvedRequestIds));
  let refreshFailure = $derived(needsYouRefreshFailureMessage(error, degradedLabels, rows.length));
  const itemId = (row: (typeof rows)[number]) => row.kind === 'permission'
    ? row.value.request.request_id
    : String(row.decision.msg_id ?? '');
  let orderedRows = $derived.by(() => {
    const selected = selectedItem;
    if (!selected) return rows;
    const index = rows.findIndex((row) => itemId(row) === selected);
    return index <= 0 ? rows : [rows[index], ...rows.slice(0, index), ...rows.slice(index + 1)];
  });
  let visibleRows = $derived(orderedRows.slice(0, limit));

  async function load() {
    try {
      const [loadedThreads, people] = await Promise.all([loadThreads(), listAgents()]);
      threads = loadedThreads.map((loaded) => {
        const { thread, decisions } = loaded;
        const item = decisions.find((decision) => decision.mailbox_open);
        const title = item ? item.title || item.asked || item.body || 'Needs your response' : '';
        const agentId = String(item?.sender ?? thread.sender);
        const label = String(item?.agent_title || people.find((agent) => agent.agent_id === agentId)?.name || '');
        const permissionText = item?.kind === 'permission'
          ? [item.title, item.asked, item.body].map((value) => String(value ?? '')).find((value) => /^(?:run|execute)\s+(?:command|tool)\s*:/i.test(value.trim())) || title
          : title;
        const displayTitle = item?.kind === 'permission' ? permissionTitle(agentId, permissionText, label) : title;
        return { ...loaded, thread: item?.kind === 'permission' ? { ...thread, title: displayTitle } : thread, decisions, title: displayTitle };
      });
      agents = people;
      cacheWrite('varde:cache:needs-you:v1', { threads, agents });
      error = '';
    } catch (e) { error = e instanceof Error ? e.message : 'Could not load mail'; }
    finally {
      try {
        const response = await fetch('/api/degraded');
        if (!response.ok) throw new Error('Could not load degraded sources');
        const data: { sources?: unknown } = await response.json();
        degraded = Array.isArray(data.sources) ? data.sources.filter((source): source is string => typeof source === 'string') : [];
      } catch { degraded = []; }
      loading = false;
    }
  }
  async function retryLoad() {
    retrying = true;
    await load();
    retrying = false;
  }
  async function answer(agent: Agent, requestId: string, decision: string) {
    const key = `${agent.agent_id}:${requestId}`;
    answering = key;
    try {
      const writer = await openAgentWriter(agent.agent_id, () => {});
      try { await respondAgent(agent.agent_id, writer, requestId, decision); }
      finally { writer.close(); }
      answered = { ...answered, [`${agent.agent_id}:${requestId}`]: decision };
      setTimeout(async () => {
        resolvedRequestIds = new Set([...resolvedRequestIds, requestId]);
        await load();
        onsettled();
        answered = Object.fromEntries(Object.entries(answered).filter(([key]) => key !== `${agent.agent_id}:${requestId}`));
      }, 300);
    } catch (e) { error = e instanceof Error ? e.message : 'Could not answer permission request'; }
    finally { answering = ''; }
  }
  async function answerMailbox(id: string, option: string, text = '') {
    mailboxSending = id;
    mailboxConfirmation = '';
    try {
      const response = await fetch(`/api/mailbox/${encodeURIComponent(id)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option: option || undefined, text, idempotency_key: crypto.randomUUID() }),
      });
      if (!response.ok) throw new Error(`Send failed (${response.status})`);
      const answerText = needsYouAnswerText(text, option);
      try { localStorage.setItem(`varde:sent:${id}`, JSON.stringify({ text: answerText, sent_at: new Date().toISOString() })); } catch { /* The answer is still sent to the server. */ }
      await load();
      mailboxSending = '';
      mailboxConfirmation = 'Your answer was sent.';
      replying.delete(id);
      replying = new Set(replying);
      onsettled();
    } catch (e) { error = e instanceof Error ? e.message : 'Could not answer this item'; }
    finally { mailboxSending = ''; }
  }
  async function dismissMailbox(id: string) {
    try {
      const response = await fetch(`/api/mailbox/${encodeURIComponent(id)}/dismiss`, { method: 'POST' });
      if (!response.ok) throw new Error(`Dismiss failed (${response.status})`);
      await load();
      onsettled();
    } catch (e) { error = e instanceof Error ? e.message : 'Could not dismiss this item'; }
  }
  function actionTitle(thread: ThreadMail['thread'], item: Record<string, unknown> | undefined): string {
    if (!chat) return thread.title || thread.sender || 'Message needs your attention';
    const itemTitle = String(item?.title || item?.asked || item?.body || 'Message needs your attention');
    if (item?.kind === 'permission') return itemTitle;
    const sender = typeof item?.agent_title === 'string' ? item.agent_title : agents.find((agent) => agent.agent_id === item?.agent)?.name || senderName(typeof item?.agent === 'string' ? item.agent : thread.sender);
    return `${sender} · ${itemTitle}`;
  }
  function showReply(id: string) { replying = new Set([...replying, id]); }
  function sendReply(event: SubmitEvent, id: string, option = '') {
    event.preventDefault();
    const input = (event.currentTarget as HTMLFormElement).querySelector<HTMLInputElement>('input.reply');
    void answerMailbox(id, option || mailboxOptions[id] || '', input?.value.trim() ?? '');
  }
  onMount(() => {
    const cached = cacheRead<{ threads: ThreadMail[]; agents: Agent[] }>('varde:cache:needs-you:v1', 10 * 60 * 1000);
    if (cached && Array.isArray(cached.threads) && Array.isArray(cached.agents)) { threads = cached.threads.map(normalizeThreadMail).filter((thread): thread is ThreadMail => thread !== null); agents = cached.agents; loading = false; }
    load();
    const stopSnapshot = onSnapshot(['mailbox'], load);
    return stopSnapshot;
  });
</script>

<section class="needs work-list" class:chat-needs={chat} class:empty-list={!error && rows.length === 0} aria-label={chat ? 'Needs action' : 'Needs you'}>
  {#if chat && mailboxConfirmation}<p class="mailbox-confirmation" role="status">{mailboxConfirmation}</p>{/if}
  {#if !refreshFailure && other.length}<p class="other-mail"><Button href="/threads" variant="link">Other conversations ({other.length}), no action needed</Button></p>{/if}
  {#if !refreshFailure && degradedLabels.length}<p class="degraded" role="status">Some data could not be refreshed ({degradedLabels.join(', ')}); this list may be incomplete.</p>{/if}
  {#if loading && !rows.length}<div aria-busy="true"><Skeleton rows={3} card /></div>
  {:else if refreshFailure}<Card><div class="refresh-failure"><p class="error" role="alert">{refreshFailure}</p><Button variant="secondary" disabled={retrying} onclick={retryLoad}>{retrying ? 'Retrying…' : 'Retry'}</Button></div></Card>
  {:else if rows.length}
    <div class="cards">{#each visibleRows as row (`${row.kind}:${row.kind === 'permission' ? `${row.value.agent.agent_id}:${row.value.request.request_id}` : `${row.value.thread.thread_id}:${row.decision.msg_id}`}`)}
      {#if row.kind === 'permission'}
        {@const { agent, request } = row.value}
        {@const state = answerState(`${agent.agent_id}:${request.request_id}`, answering, answered)}
        <div transition:slide={{ duration: 300 }}><Card><article class="permission work-item" data-answer-card data-answer={state}><div><h2>{permissionTitle(agent.agent_id, request.summary, agent.name || agent.role || agent.agent_id)}</h2><p>Review this request from the conversation.</p><p>{agent.name || agent.role || agent.agent_id}</p>{#if state === 'approved'}<p class="answer-status" role="status">Approved</p>{:else if state === 'denied'}<p class="answer-status" role="status">Denied</p>{:else if state === 'sending'}<p class="answer-status" role="status">Saving…</p>{/if}</div>{#if state === 'idle'}<div class="actions"><Button size="sm" variant="primary" disabled={answering !== ''} onclick={() => answer(agent, request.request_id, 'allow')}>Allow</Button><Button size="sm" variant="secondary" class="danger" disabled={answering !== ''} onclick={() => answer(agent, request.request_id, 'deny')}>Deny</Button></div>{/if}</article></Card></div>
      {:else}
        {@const item = mailDecision(row.decision)}
        {@const action = mailboxItemAction(item)}
        {@const detail = item.asked || item.body || item.title || row.value.thread.title || row.value.thread.last_preview}
        <div transition:slide={{ duration: 300 }}><Card><article class="work-item" data-answer-card>
          <h2>{actionTitle(row.value.thread, item)}</h2>
          <p class="question-text">{detail}</p>
          {#if !chat}<p>{item?.agent || row.value.thread.sender}</p>{/if}
          {#if chat && action === 'question'}
            <form class="reply-form" onsubmit={(event) => sendReply(event, item.msg_id)}>
              {#if item.options?.length}<div class="question-options" role="radiogroup" aria-label="Answer options">{#each item.options as option}<label><input type="radio" name={`answer-${item.msg_id}`} value={needsYouOptionLabel(option)} checked={mailboxOptions[item.msg_id] === needsYouOptionLabel(option)} onchange={(event) => mailboxOptions = { ...mailboxOptions, [item.msg_id]: event.currentTarget.value }} />{needsYouOptionLabel(option)}</label>{/each}</div>{/if}
              <input class="reply" aria-label={`Answer ${item.agent || row.value.thread.sender}`} placeholder="Write your answer…" value={mailboxReplies[item.msg_id] ?? ''} oninput={(event) => mailboxReplies = { ...mailboxReplies, [item.msg_id]: event.currentTarget.value }} disabled={mailboxSending === item.msg_id} />
              <Button size="sm" variant="primary" type="submit" aria-describedby={mailboxSending !== item.msg_id && !mailboxOptions[item.msg_id] && !mailboxReplies[item.msg_id]?.trim() ? `send-reason-${item.msg_id}` : undefined} disabled={mailboxSending === item.msg_id || (!mailboxOptions[item.msg_id] && !mailboxReplies[item.msg_id]?.trim())}>{mailboxSending === item.msg_id ? 'Sending…' : 'Send'}</Button>
              {#if mailboxSending !== item.msg_id && !mailboxOptions[item.msg_id] && !mailboxReplies[item.msg_id]?.trim()}<small id={`send-reason-${item.msg_id}`} class="action-reason">Choose an option or write an answer to enable Send.</small>{/if}
            </form>
          {:else if chat && item && replying.has(item.msg_id)}
            <form class="reply-form" onsubmit={(event) => sendReply(event, item.msg_id, action === 'permission' ? 'ask-more' : '')}>
              <input class="reply" aria-label={`Reply to ${item.agent || row.value.thread.sender}`} placeholder="Write a reply…" />
              <Button size="sm" variant="primary" type="submit">Send</Button>
            </form>
          {:else if chat && action === 'permission'}
            <div class="actions"><Button size="sm" variant="primary" onclick={() => void answerMailbox(item.msg_id, 'allow')}>Allow</Button><Button size="sm" variant="secondary" class="danger" onclick={() => void answerMailbox(item.msg_id, 'deny')}>Deny</Button><Button size="sm" variant="secondary" onclick={() => showReply(item.msg_id)}>Reply</Button></div>
          {:else if chat}
            <div class="actions"><Button size="sm" variant="primary" href={`/threads/${encodeURIComponent(row.value.thread.thread_id)}`}>Open</Button></div>
          {:else if item?.type === 'question'}
            <form class="reply-form" onsubmit={(event) => {
              event.preventDefault();
              const input = (event.currentTarget as HTMLFormElement).querySelector('input');
              void answerMailbox(item.msg_id, '', input?.value.trim() ?? '');
            }}>
              <input class="reply" aria-label={`Reply to ${item.agent}`} placeholder="Write a reply…" />
              <Button size="sm" variant="primary" type="submit">Send reply</Button>
            </form>
          {:else}
            <div class="actions">
            {#if item?.type === 'approval'}
              <Button size="sm" variant="primary" onclick={() => void answerMailbox(item.msg_id, 'allow')}>Allow</Button>
              <Button size="sm" variant="secondary" class="danger" onclick={() => void answerMailbox(item.msg_id, 'deny')}>Deny</Button>
            {:else if item?.type === 'failed'}
              <Button size="sm" variant="primary" href={`/threads/${encodeURIComponent(row.value.thread.thread_id)}`}>Retry</Button>
              <Button size="sm" variant="secondary" class="danger" onclick={() => void dismissMailbox(item.msg_id)}>Dismiss</Button>
            {:else}
              <Button size="sm" variant="primary" href={`/threads/${encodeURIComponent(row.value.thread.thread_id)}`}>Open</Button>
            {/if}
            </div>
          {/if}
        </article></Card></div>
      {/if}
    {/each}</div>
  {:else}<section class="empty" aria-label="All caught up"><div class="empty-icon" aria-hidden="true">✓</div><strong>All caught up</strong><span>Nothing needs your attention right now.</span></section>{/if}
</section>
<style>
  .needs{display:grid;gap:var(--space-2);min-width:0}.empty-list{flex:1;grid-template-rows:1fr}.cards{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;min-width:0}
  .other-mail{margin:0;text-align:right}
  .empty{min-height:240px;display:grid;place-content:center;text-align:center;color:var(--cf-muted);font-size:17px;line-height:1.4}.empty strong{font-size:19px;color:var(--cf-text)}.empty span{margin-top:7px}.empty-icon{font-size:32px;margin-bottom:12px}
  .error,.degraded{margin:0;color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .refresh-failure{display:grid;justify-items:start;gap:var(--space-3)}
  .work-item{display:grid;gap:8px;min-width:0}.permission>div:first-child{display:grid;gap:8px}.work-item h2,.work-item p{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.work-item h2{margin:0;font-size:17px;font-weight:700}.work-item p{margin:0;color:var(--cf-muted);font-size:15px;line-height:1.4}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:2px}
  :global(.needs .card){padding:16px;border:0;border-radius:20px;background:var(--cf-panel);box-shadow:var(--cf-shadow)}
  :global(.work-item .ui-button){height:48px;min-height:48px;padding:0 18px;border:0;border-radius:999px;background:var(--cf-soft);color:var(--cf-text);font-size:15px;font-weight:650}
  :global(.work-item .ui-button.sm){padding:0 18px}
  :global(.reply-form .ui-button){justify-self:start}
  :global(.work-item .ui-button.primary){background:var(--cf-primary);color:var(--cf-primary-ink)}
  :global(.work-item .ui-button.danger){color:var(--cf-bad)}
  .reply-form{display:grid;gap:10px;margin-top:-8px}.reply{box-sizing:border-box;width:100%;min-width:0;height:48px;padding:0 14px;border:1px solid var(--cf-line);border-radius:999px;background:var(--cf-panel);color:var(--cf-text);font:inherit}
  .answer-status{margin:0;color:var(--status-success-fg)}.permission{display:grid;gap:8px}
  .chat-needs{display:block;padding:6px 16px 28px}
  .mailbox-confirmation{margin:0 0 8px;color:var(--status-success-fg);font-size:var(--font-size-sm)}
  .chat-needs .cards{gap:9px}
  .chat-needs .work-item{gap:0}
  .chat-needs .work-item h2{font-size:15px;font-weight:700;overflow:visible;text-overflow:clip;white-space:normal;overflow-wrap:break-word}
  .chat-needs .work-item p{margin:4px 0 0;font-size:13px;line-height:1.4}
  .chat-needs .work-item .question-text{overflow:visible;text-overflow:clip;white-space:pre-wrap;overflow-wrap:anywhere}
  .question-options{display:grid;gap:var(--space-2);margin-top:var(--space-2)}.question-options label{display:flex;align-items:center;gap:var(--space-2);min-height:var(--control-h);padding:var(--space-2) var(--space-3);border:var(--line) solid var(--cf-line);border-radius:var(--radius-card);cursor:pointer}.question-options input{width:var(--space-5);height:var(--space-5);flex:none}
  .chat-needs .actions{gap:8px;margin-top:12px}
  .chat-needs :global(.card){padding:12px;border:0;border-radius:16px;background:var(--cf-panel);box-shadow:0 8px 24px #0000000d}
  .chat-needs :global(.work-item .ui-button){height:44px;min-height:44px;padding:0 16px;font-size:14px}
  .chat-needs :global(.work-item .ui-button.primary){background:var(--cf-text);color:var(--cf-bg)}
  .chat-needs :global(.work-item .ui-button:disabled){background:var(--surface-disabled);border-color:var(--border-strong);color:var(--text)}
  .action-reason{color:var(--text-muted);font-size:var(--font-size-xs)}
  :global(:root[data-theme=dark]) .chat-needs :global(.card){box-shadow:inset 0 0 0 1px #ffffff0d}
</style>
