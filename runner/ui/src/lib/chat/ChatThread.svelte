<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { cacheRead, cacheWrite } from '../cache';
  import Skeleton from '../ui/Skeleton.svelte';
  import { openAgentWriter, respondAgent } from '../agentsApi';
  import Markdown from '../ui/Markdown.svelte';
  import BotControls from '../BotControls.svelte';
  import InlineApproval from './InlineApproval.svelte';
  import { controlBot, getBotAudit, type BotSnapshot } from '../botApi';
  import { getHistory, openChatStream, sendMessage, type ChatBotInfo } from './chatApi';
  import { isUserFacingMessage, loadDraft, loadOutbox, mergeMessages, pageWindow, resumeCursor, saveDraft, saveOutbox, shouldFollow, upsertOutbox, type ChatMessage, type OutboxItem } from './chatState';
  import { delegationRows } from './delegationRows';
  import { managerStatus } from './managerStatus';

  type InstanceActivity = { label: string; state: string; last_activity: string | null; pending_count: number };
  let { threadKey = 'main', compact = false, hideHeader = false, composerLabel = 'Message', roleEnabled = null, instanceActivity = [] }: { threadKey?: string; compact?: boolean; hideHeader?: boolean; composerLabel?: string; roleEnabled?: boolean | null; instanceActivity?: InstanceActivity[] } = $props();
  let messages = $state<ChatMessage[]>([]);
  let bot = $state<ChatBotInfo>({ state: 'unavailable', context_pct: null, generation: 0 });
  let botControl = $state<BotSnapshot | null>(null);
  let controlError = $state('');
  let draft = $state('');
  let error = $state('');
  let loading = $state(true);
  let olderLoading = $state(false);
  let hasOlder = $state(false);
  let newMessages = $state(false);
  let outbox = $state<OutboxItem[]>([]);
  let messageList: HTMLDivElement;
  let composer: HTMLTextAreaElement;
  let streamStop: (() => void) | undefined;
  let pinned = true;
  let answering = $state(new Set<string>());
  let auditRows = $state<Awaited<ReturnType<typeof getBotAudit>>>([]);
  let delegationItems = $derived(threadKey === 'main' ? delegationRows(auditRows, messages) : []);
  let visibleMessages = $derived((compact ? messages.slice(-10) : messages).filter(isUserFacingMessage));
  let manager = $derived(threadKey !== 'main' ? null : roleEnabled === false ? managerStatus({ roleEnabled: false }) : loading ? null : managerStatus({ chatState: bot.state, governorState: botControl?.state ?? null, reason: botControl?.reason ?? null, roleEnabled: roleEnabled ?? true }));
  let composerDisabled = $derived(Boolean(manager?.composerDisabled));
  let composerDescriptionIds = $derived(composerDisabled ? 'composer-hint composer-notice' : 'composer-hint');

  function isDelegationLine(text: string): boolean {
    return delegationItems.some((item) => item.text === text);
  }

  function updateScrollState() {
    if (!messageList) return;
    const distance = messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight;
    pinned = shouldFollow(distance);
    if (pinned) newMessages = false;
  }

  function visibleAnchor(): number {
    if (pinned) return messages.at(-1)?.seq ?? 0;
    const firstVisible = [...(messageList?.querySelectorAll<HTMLElement>('[data-seq]') ?? [])]
      .find((element) => element.getBoundingClientRect().bottom > messageList.getBoundingClientRect().top);
    return Number(firstVisible?.dataset.seq ?? messages[0]?.seq ?? 0);
  }

  function persistOutbox(items: OutboxItem[]) {
    outbox = items;
    saveOutbox(threadKey, items);
  }

  async function refreshDelegations() {
    if (threadKey !== 'main') return;
    try { auditRows = await getBotAudit(); } catch { /* Audit rows are supplemental to the chat. */ }
  }

  function markMainRead(latest: number) {
    if (threadKey !== 'main') return;
    try { localStorage.setItem('varde:chat:main:seen', String(latest)); } catch { /* Best effort. */ }
    window.dispatchEvent(new CustomEvent('runner:chat-read'));
  }

  async function scrollToBottom() {
    await tick();
    if (messageList) messageList.scrollTop = messageList.scrollHeight;
    pinned = true;
    newMessages = false;
  }

  function applyStream(event: Parameters<Parameters<typeof openChatStream>[2]>[0]) {
    if (event.type === 'message') {
      const followed = pinned;
      messages = pageWindow(mergeMessages(messages, [event.message]), visibleAnchor());
      markMainRead(event.message.seq);
      if (event.message.role === 'bot' && !followed) newMessages = true;
      if (event.message.role === 'bot') void refreshDelegations();
      if (followed) void scrollToBottom();
    } else if (event.type === 'delta') {
      const index = messages.findIndex((message) => message.id === event.id);
      if (index >= 0 && event.rev >= messages[index].change_seq) {
        const updated = { ...messages[index], text: messages[index].text + event.text_append, change_seq: event.rev };
        messages = pageWindow(messages.map((message, itemIndex) => itemIndex === index ? updated : message), visibleAnchor());
        if (updated.role === 'bot') {
          if (pinned) void scrollToBottom();
          else newMessages = true;
        }
      }
    } else if (event.type === 'bot') {
      bot = event.bot;
      if (botControl) botControl = { ...botControl, state: event.bot.state as BotSnapshot['state'] };
    }
  }

  async function resumeBot() {
    controlError = '';
    try {
      botControl = await controlBot('resume');
      bot = { ...bot, state: botControl.state };
    }
    catch (cause) { controlError = cause instanceof Error ? cause.message : 'Could not resume the bot.'; }
  }

  async function loadOlder() {
    if (olderLoading || !hasOlder || !messages.length) return;
    olderLoading = true;
    const beforeHeight = messageList?.scrollHeight ?? 0;
    const before = messages[0].seq;
    try {
      const history = await getHistory(threadKey, before);
      messages = pageWindow(mergeMessages(history.messages, messages), visibleAnchor() || before);
      hasOlder = history.messages.length === 50;
      await tick();
      if (messageList) messageList.scrollTop += messageList.scrollHeight - beforeHeight;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Could not load earlier messages.';
    } finally { olderLoading = false; }
  }

  function makeId() {
    return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function optimisticMessage(id: string, text: string): ChatMessage {
    const seq = (messages.at(-1)?.seq ?? 0) + 1;
    return { seq, change_seq: -1, id, thread_key: threadKey, reply_to: null, role: 'user', kind: null, text, link: null, state: 'sending', source_agent_id: null, source_event_seq: null, created_at: new Date().toISOString(), delivery: 'sending' };
  }

  async function submit(id?: string) {
    if (composerDisabled) return;
    const text = outbox.find((item) => item.id === id)?.text ?? draft.trim();
    if (!text || !text.trim()) return;
    const messageId = id ?? makeId();
    if (!id) {
      messages = pageWindow(mergeMessages(messages, [optimisticMessage(messageId, text)]), messages.at(-1)?.seq ?? 0);
      persistOutbox(upsertOutbox(outbox, { id: messageId, text, state: 'sending' }));
      draft = '';
      saveDraft(threadKey, '');
      resizeComposer();
    } else {
      persistOutbox(upsertOutbox(outbox, { id: messageId, text, state: 'sending' }));
      messages = messages.map((message) => message.id === messageId ? { ...message, delivery: 'sending', state: 'sending' } : message);
    }
    error = '';
    await scrollToBottom();
    try {
      const sent = await sendMessage(threadKey, messageId, text);
      messages = messages.map((message) => message.id === messageId ? { ...message, id: sent.id, seq: sent.seq, state: 'sent', delivery: 'sent' } : message);
      persistOutbox(outbox.filter((item) => item.id !== messageId));
    } catch (cause) {
      messages = messages.map((message) => message.id === messageId ? { ...message, state: 'failed', delivery: 'failed' } : message);
      persistOutbox(upsertOutbox(outbox, { id: messageId, text, state: 'failed' }));
      error = cause instanceof Error ? cause.message : 'Message could not be sent.';
    }
  }

  function discard(id: string) {
    messages = messages.filter((message) => message.id !== id);
    persistOutbox(outbox.filter((item) => item.id !== id));
  }

  function updateDraft(value: string) {
    draft = value;
    saveDraft(threadKey, value);
    resizeComposer();
  }

  function resizeComposer() {
    if (!composer) return;
    composer.style.height = 'auto';
    const maxHeight = Number.parseFloat(getComputedStyle(composer).maxHeight);
    composer.style.overflowY = composer.scrollHeight > maxHeight ? 'auto' : 'hidden';
    composer.style.height = `${Math.min(composer.scrollHeight, Number.isFinite(maxHeight) ? maxHeight : composer.scrollHeight)}px`;
  }

  function questionId(message: ChatMessage): string | null {
    if (message.kind !== 'question' || !threadKey.startsWith('instance:') || !message.link) return null;
    try { return new URL(message.link, 'http://localhost').searchParams.get('request_id'); }
    catch { return null; }
  }

  function isAnswered(requestId: string): boolean {
    return messages.some((message) => {
      if (message.role !== 'event' || message.kind !== 'answer' || !message.link?.startsWith('request:')) return false;
      try { return decodeURIComponent(message.link.slice('request:'.length)) === requestId; }
      catch { return false; }
    });
  }

  async function answer(requestId: string, decision: string) {
    const agentId = threadKey.slice('instance:'.length);
    answering = new Set([...answering, requestId]);
    error = '';
    let writer: Awaited<ReturnType<typeof openAgentWriter>> | undefined;
    try {
      writer = await openAgentWriter(agentId, () => {});
      await respondAgent(agentId, writer, requestId, decision);
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not answer this question.'; }
    finally { writer?.close(); answering.delete(requestId); answering = new Set(answering); }
  }

  function onComposerKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void submit();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      composer?.blur();
    } else if (event.key === 'End' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void scrollToBottom();
    }
  }

  function revealComposer() {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!composer || document.activeElement !== composer) return;
      const viewport = window.visualViewport;
      const visibleBottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight;
      if (composer.getBoundingClientRect().bottom > visibleBottom && messageList) {
        messageList.scrollTop = messageList.scrollHeight;
      }
    }));
  }

  onMount(() => {
    let active = true;
    const cacheKey = `varde:cache:chat-history:${encodeURIComponent(threadKey)}:v1`;
    const cachedMessages = cacheRead<ChatMessage[]>(cacheKey, 10 * 60 * 1000);
    if (cachedMessages) { messages = cachedMessages; loading = false; }
    if (threadKey === 'main') void refreshDelegations();
    draft = loadDraft(threadKey);
    resizeComposer();
    outbox = loadOutbox(threadKey);
    getHistory(threadKey).then(async (history) => {
      if (!active) return;
      messages = pageWindow(history.messages, history.messages.at(-1)?.seq ?? 0);
      cacheWrite(cacheKey, history.messages);
      const visibleIds = new Set(messages.map((message) => message.id));
      persistOutbox(outbox.filter((item) => !visibleIds.has(item.id)));
      const nextSeq = (messages.at(-1)?.seq ?? 0) + 1;
      messages = mergeMessages(messages, outbox.map((item, index) => ({ seq: nextSeq + index, change_seq: -1, id: item.id, thread_key: threadKey, reply_to: null, role: 'user' as const, kind: null, text: item.text, link: null, state: 'failed', source_agent_id: null, source_event_seq: null, created_at: new Date().toISOString(), delivery: 'failed' as const })));
      messages = pageWindow(messages, messages.at(-1)?.seq ?? 0);
      hasOlder = history.messages.length === 50;
      bot = history.bot;
      loading = false;
      resizeComposer();
      markMainRead(history.latest_seq);
      await scrollToBottom();
      streamStop = openChatStream(threadKey, resumeCursor(messages), applyStream, () => {}, () => {});
    }).catch((cause) => {
      if (!active) return;
      error = cause instanceof Error ? cause.message : 'Could not load chat.';
      loading = false;
    });
    const shortcuts = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !compact) {
        event.preventDefault();
        composer?.focus({ preventScroll: true });
      }
    };
    window.addEventListener('keydown', shortcuts);
    return () => { active = false; streamStop?.(); window.removeEventListener('keydown', shortcuts); };
  });
</script>

<section class:compact class="thread chat-thread" data-zone="thread" aria-label="Chat">
  {#if !compact && threadKey === 'main'}
    {#if hideHeader}
      {#if roleEnabled !== false && roleEnabled !== null}<BotControls bind:snapshot={botControl} contextPct={bot.context_pct} />{:else if roleEnabled !== false}<span class="bot-controls-space" aria-hidden="true"></span>{/if}
    {:else}
      <header class="chat-header"><h1>Manager bot</h1>{#if roleEnabled !== false && roleEnabled !== null}<BotControls bind:snapshot={botControl} contextPct={bot.context_pct} />{:else if roleEnabled !== false}<span class="bot-controls-space" aria-hidden="true"></span>{/if}</header>
    {/if}
  {/if}
  {#if controlError}<div class="error" role="alert">{controlError}</div>{/if}
  {#if error}<div class="error" role="alert">{error}</div>{/if}
  <div class="messages" bind:this={messageList} onscroll={updateScrollState} role="log" aria-label="Messages" aria-live="off" tabindex="-1">
    {#if instanceActivity.length > 0}
      <details class="instance-activity">
        <summary>{instanceActivity.length} {instanceActivity.length === 1 ? 'instance' : 'instances'} · {instanceActivity.filter((item) => item.pending_count > 0).reduce((sum, item) => sum + item.pending_count, 0)} pending</summary>
        <ul>{#each instanceActivity as instance (`${instance.label}:${instance.last_activity ?? ''}`)}<li><strong>{instance.label}</strong><span>{instance.state}{instance.pending_count ? ` · ${instance.pending_count} pending` : ''}</span></li>{/each}</ul>
      </details>
    {/if}
    {#if hasOlder}<button class="older" type="button" onclick={loadOlder} disabled={olderLoading}>{olderLoading ? 'Loading…' : 'Load earlier messages'}</button>{/if}
    {#if loading && messages.length === 0}<div aria-busy="true"><Skeleton rows={4} /></div>{:else if !loading && messages.length === 0 && !error && threadKey === 'main' && roleEnabled === false}<section class="manager-off-state"><h2>Start a manager conversation</h2><p>Manager bot is off. Start it to chat.</p><a href="/settings">Start</a></section>{:else if !loading && messages.length === 0 && !error}<p class="state">No messages yet. Start the conversation.</p>{/if}
    {#each visibleMessages as message (message.id)}
      {#if message.role === 'event'}
        {#if message.kind !== 'answer'}
          {#if questionId(message)}<article class="question"><p>{message.text}</p>{#if isAnswered(questionId(message)!)}<small>Answered</small>{:else}<div><button type="button" disabled={answering.has(questionId(message)!)} onclick={() => answer(questionId(message)!, 'allow')}>Allow</button><button type="button" disabled={answering.has(questionId(message)!)} onclick={() => answer(questionId(message)!, 'deny')}>Deny</button></div>{/if}</article>
          {:else}<div class="event-row" title={message.text}>{#if message.link && message.kind === 'handoff'}<a href={message.link}>{message.text}</a>{:else}{message.text}{/if}</div>{/if}
        {/if}
      {:else if message.role === 'bot' && isDelegationLine(message.text)}
        <!-- The audit-backed delegation row below replaces its matching chat line. -->
      {:else}
        <article class="message" class:user={message.role === 'user'} aria-live={message.role === 'bot' ? 'polite' : 'off'} data-seq={message.seq}>
          <div class="message-meta"><span>{message.role === 'user' ? 'You' : 'Varde'}</span><time datetime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div>
          <Markdown text={message.text} />
          {#if message.delivery === 'sending'}<small>Sending…</small>{:else if message.delivery === 'failed'}<div class="failed"><span>Not sent</span><button type="button" onclick={() => submit(message.id)}>Retry</button><button type="button" onclick={() => discard(message.id)}>Discard</button></div>{/if}
        </article>
      {/if}
    {/each}
    {#if threadKey === 'main'}<InlineApproval {threadKey} {messages} />{/if}
    {#if threadKey === 'main' && delegationItems.length}
      <div class="delegation-list" aria-label="Recent manager actions">
        {#each delegationItems as item (item.id)}
          <div class="delegation-row"><span>↗ {item.text}</span><time datetime={item.ts}>{new Date(item.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div>
        {/each}
      </div>
    {/if}
    {#if newMessages}<button class="new-messages" type="button" onclick={scrollToBottom}>New messages</button>{/if}
  </div>
  {#if threadKey !== 'main' || roleEnabled !== false}
  <div id="composer-notice" class="notice" role="status">{#if composerDisabled}{manager?.reason}{#if manager?.href} <a href={manager.href}>Open Settings</a>{/if}{/if}</div>
  {#if threadKey === 'main' && (bot.state === 'paused' || botControl?.state === 'paused')}<div class="notice" role="status">Chat is paused{#if botControl?.reason}: {botControl.reason}{/if}. Your message will be queued.{#if botControl?.state === 'paused'} <button type="button" onclick={resumeBot}>Resume</button>{/if}</div>{/if}
  <form class="composer" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
    <label class="visually-hidden" for="chat-message">{composerLabel}</label>
    <span id="composer-hint" class="visually-hidden">Enter to send. Shift+Enter for a new line.</span>
    <textarea id="chat-message" aria-describedby={composerDescriptionIds} bind:this={composer} value={draft} onfocus={revealComposer} oninput={(event) => updateDraft(event.currentTarget.value)} onkeydown={onComposerKeydown} maxlength="20000" placeholder={composerLabel} rows="1" disabled={composerDisabled}></textarea>
    <button class="send" type="submit" aria-label="Send message" disabled={composerDisabled || !draft.trim()}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg></button>
    <p class="hint">Enter to send · Shift+Enter for a new line</p>
  </form>
  {/if}
</section>

<style>
  .chat-thread{position:relative;display:flex;flex-direction:column;min-width:0;height:100%;min-height:0;overflow:visible;background:transparent;color:var(--cf-text)}
  .chat-header{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:var(--space-2);min-width:0;border-bottom:var(--line) solid var(--border-subtle)}
  .chat-header h1{margin:0;padding-inline:16px;color:var(--text-strong);font-size:var(--font-size-lg);white-space:nowrap}
  .chat-header :global(.controls){padding-inline:0;border:0}
  .bot-controls-space{display:block;flex:none;min-height:calc(var(--control-h) + var(--space-4))}
  .manager-off-state{box-sizing:border-box;display:grid;width:min(100%,36rem);justify-self:center;justify-items:start;gap:var(--space-2);margin:var(--space-4) auto auto;padding:var(--space-5);border:var(--line) solid var(--border-subtle);border-radius:var(--radius-card);background:var(--surface-1)}
  .manager-off-state h2,.manager-off-state p{margin:0}.manager-off-state p{color:var(--text-muted)}
  .manager-off-state a{display:inline-flex;align-items:center;min-height:var(--control-h);padding-inline:var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);font-weight:650;text-decoration:none}
  .compact{height:100%;min-height:260px;border:0;border-radius:0;background:transparent}
  .messages{display:flex;flex:1;min-height:0;flex-direction:column;gap:var(--space-3);overflow:auto;padding:var(--space-4);overscroll-behavior:contain;overflow-anchor:auto;scrollbar-gutter:stable}
  .instance-activity{padding:10px 12px;border:1px solid var(--cf-line);border-radius:10px;background:var(--cf-panel);font-size:var(--font-size-sm)}.instance-activity summary{cursor:pointer;color:var(--cf-text);font-weight:600}.instance-activity ul{display:grid;gap:6px;margin:10px 0 0;padding:0;list-style:none}.instance-activity li{display:flex;justify-content:space-between;gap:12px;color:var(--cf-muted)}.instance-activity li strong{color:var(--cf-text);font-weight:500}
  .chat-thread:not(.compact) .messages{padding:0 var(--space-4) var(--space-4)}
  .message{max-width:92%;padding:var(--space-3) var(--space-4);border:0;border-radius:20px 20px 20px 6px;background:var(--cf-soft);color:var(--cf-text);overflow-wrap:anywhere;content-visibility:auto;contain-intrinsic-size:auto 110px;animation:bubble-in 160ms ease both}
  .compact .message{max-width:min(88%,760px)}
  .message.user{align-self:flex-end;border-radius:20px 20px 6px 20px;background:var(--cf-primary);color:var(--cf-primary-ink)}
  .message :global(.markdown){font-size:17px;line-height:1.4;color:inherit}
  .message-meta{display:flex;justify-content:space-between;gap:var(--space-3);margin-bottom:var(--space-2);color:var(--cf-muted);font-size:var(--font-size-xs)}.chat-thread:not(.compact) .message-meta{display:none}
  .message small{display:block;margin-top:var(--space-2);color:var(--cf-muted)}
  .event-row{align-self:center;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted);font-size:var(--font-size-xs);padding:var(--space-1) var(--space-3)}
  .delegation-list{align-self:stretch;display:grid;gap:var(--space-1);width:100%}.delegation-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);min-width:0;padding:12px 16px;border:0;border-radius:12px;background:var(--cf-panel);color:var(--cf-muted);font-size:15px}.delegation-row span{min-width:0;overflow-wrap:anywhere}.delegation-row time{display:none;flex:none}
  .question{align-self:flex-start;display:grid;gap:var(--space-2);max-width:min(100%,600px);padding:var(--space-3);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1)}.question p{margin:0;overflow-wrap:anywhere}.question div{display:flex;gap:var(--space-2)}.question button{min-height:var(--control-h);padding-inline:var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);cursor:pointer}.question small{color:var(--text-muted)}
  .state{margin:auto;color:var(--text-muted);font-size:var(--font-size-sm)}
  .older,.new-messages,.failed button{min-height:var(--control-h);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);padding:0 var(--space-3);cursor:pointer}
  .older{align-self:center}.new-messages{position:sticky;bottom:var(--space-2);align-self:center;box-shadow:var(--elevation-card);z-index:1}
  .composer{display:grid;flex:none;grid-template-columns:minmax(0,1fr) 48px;gap:var(--space-2);padding:8px 16px calc(8px + env(safe-area-inset-bottom));border-top:var(--line) solid var(--cf-line);background:var(--cf-panel)}
  textarea{box-sizing:border-box;width:100%;min-width:0;height:48px;min-height:48px;max-height:calc(1.4em * 5 + 24px + 2px);overflow-x:hidden;overflow-y:hidden;resize:none;padding:var(--space-3) var(--space-4);border:var(--line) solid var(--cf-line);border-radius:24px;background:var(--cf-bg);color:var(--cf-text);font-size:16px;line-height:1.4}
  .composer textarea{background:var(--cf-bg)}.chat-thread:not(.compact) .composer textarea{background:var(--cf-panel)}
  .send{width:48px;min-width:48px;height:48px;min-height:48px;align-self:end;border:0;border-radius:50%;background:var(--cf-primary);color:var(--cf-primary-ink);font-size:20px;font-weight:400;cursor:pointer}.chat-thread:not(.compact) .send{border-radius:999px}.send svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.send:disabled{opacity:1;background:var(--surface-disabled);border:1px solid var(--border-strong);color:var(--text-secondary);cursor:not-allowed}
  .hint{grid-column:1/-1;margin:0;color:var(--text-muted);font-size:var(--font-size-xs)}.chat-thread:not(.compact) .hint{display:none}
  .notice,.error{padding:var(--space-2) var(--space-3);font-size:var(--font-size-sm)}.notice{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);background:var(--surface-inset);color:var(--text-muted)}#composer-notice{align-items:flex-start;flex-direction:column;padding-inline:16px}.notice:empty{display:none}.notice button{min-height:var(--control-h);padding:0 var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body)}.notice a{display:inline-flex;align-items:center;min-height:44px;padding:0 var(--space-2);color:var(--accent);font-weight:600}.error{background:var(--status-blocked-bg);color:var(--status-blocked-fg)}
  .failed{display:flex;align-items:center;gap:var(--space-2);margin-top:var(--space-2);color:var(--text-danger);font-size:var(--font-size-xs)}.failed button{min-height:32px;padding-inline:var(--space-2);font-size:var(--font-size-xs)}
  .visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
  @media(prefers-reduced-motion:reduce){.message{animation:none}}
  @media(max-width:760px){.chat-thread{height:100%;min-height:0}.compact{height:100%;min-height:0}.chat-thread:not(.compact) .message{max-width:92%}.compact .messages{padding:var(--space-3)}.compact .message{max-width:96%}.compact .composer{padding:var(--space-3);padding-bottom:calc(var(--space-3) + env(safe-area-inset-bottom));background:var(--cf-panel)}.compact .composer textarea{background:var(--cf-bg)}.compact .send{border-radius:50%}.compact .hint{display:block}}
  @media(max-width:760px){.chat-thread:not(.compact) .composer{padding-bottom:calc(8px + max(0px, env(safe-area-inset-bottom) - var(--kb-inset, 0px)))}}
  @media(max-width:390px){.chat-header{grid-template-columns:1fr;gap:0}.chat-header h1{padding:var(--space-2) var(--space-3)}}
</style>
