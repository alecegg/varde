<script lang="ts">
  import { Badge, Button, Evidence, Markdown, OverflowMenu, PinnedBar, Textarea } from '../ui';
  import BackButton from '../chat/BackButton.svelte';
  import { permissionTitle, senderName } from '../chat/conversationRows';
  import { answerLabel, decisionTitle, decisionType, formatWhen, optionLabel, planOf, questionText, threadName, type Item, type Thread } from './thread';
  type Sent = { text: string; sent_at: string };
  let { thread, decisions, openIds, sent, activeId, selectedOption = $bindable(''), reply = $bindable(''), entryState, error, sending, onback, onactivate, onsend, onretry, ondismiss, onreply, onmarkunread, placement = 'fixed', showTitle = true }: {
    thread: Thread; decisions: Item[]; openIds: string[]; sent: Record<string, Sent | null>; activeId: string;
    selectedOption?: string; reply?: string; entryState: string; error: string; sending: boolean;
    onback?: () => void; onactivate: (id: string) => void; onsend: (option?: string) => void; onretry: () => void; ondismiss: (item: Item) => void; onreply: (value: string) => void; onmarkunread?: () => void; placement?: 'fixed' | 'inline';
    showTitle?: boolean;
  } = $props();
  const replyId = $derived(`reply-${encodeURIComponent(thread.thread_id)}`);
  const open = (item: Item) => item.mailbox_open !== false && openIds.includes(item.msg_id);
  const active = $derived(decisions.find((item) => item.msg_id === activeId && open(item)));
  const activeType = $derived(active ? decisionType(active) : null);
  const sourceText = (source: any) => typeof source === 'string' ? source : source?.label ?? source?.title ?? source?.path ?? source?.url ?? JSON.stringify(source);
  const badgeText = (item: Item, isOpen: boolean) => isOpen ? 'Open' : sent[item.msg_id] ? 'Answered' : item.state === 'pending' ? 'Inactive' : item.state ? item.state[0].toUpperCase() + item.state.slice(1) : 'Handled';
  const heading = (item: Item) => {
    const title = decisionTitle(item).split('\n')[0].replace(/[*_`#>]/g, '').trim();
    return item.kind === 'permission' ? permissionTitle(item.sender ?? '', title, item.agent_title) : title;
  };
  const question = (item: Item) => questionText(item) === decisionTitle(item) ? questionText(item).split('\n').slice(1).join('\n').trim() : questionText(item);
  const bodyText = (item: Item) => [question(item), item.body && item.body !== questionText(item) && item.body !== decisionTitle(item) ? item.body : ''].filter(Boolean).join('\n\n');
  const who = (item: Item) => `${item.agent_title ?? senderName(item.sender ?? 'Agent')} · ${formatWhen(item.ts)}`;
  const isRecommended = (item: Item, option: any) => Boolean(item.recommendation) && optionLabel(option) === optionLabel(item.recommendation);
  const recReason = (item: Item, option: any) => isRecommended(item, option) ? item.recommendation.reason ?? '' : '';
  const recShownOnOption = (item: Item) => Boolean(item.options?.some((option: any) => isRecommended(item, option)));
  const staleNote = (item: Item) => `Sender is no longer active (its plan concluded or it is no longer bound), so this cannot be answered. Last activity ${formatWhen(item.ts)}.`;
  const isChosen = (item: Item, option: any) => Boolean(sent[item.msg_id]) && sent[item.msg_id]!.text.trim() === optionLabel(option);
  const delivery = (item: Item) => `${item.state && item.state !== 'pending' ? item.state[0].toUpperCase() + item.state.slice(1) : 'Delivered'} ${formatWhen(sent[item.msg_id]?.sent_at)} to ${senderName(item.sender ?? 'Agent')}`;
  const status = $derived(entryState === 'failed' ? error || 'Failed' : entryState === 'delivered' ? 'Sent' : entryState === 'draft' ? '' : entryState);
  const needsRetry = $derived(entryState === 'failed' || entryState === 'stored');
  const questions = $derived(`Thread, ${decisions.length} ${decisions.length === 1 ? 'question' : 'questions'}`);
  function chooseOption(item: Item, option: any) { onactivate(item.msg_id); selectedOption = optionLabel(option); }
  const noteInput = (event: Event) => onreply((event.currentTarget as HTMLTextAreaElement).value);
</script>
<div class="thread">
  <header class="thread-head">
    {#if onback}<BackButton label="Back to threads" onclick={onback} />{/if}
    <div class="titles">{#if showTitle}<h1>{threadName(thread)}</h1>{/if}<p>{questions}</p></div>
    <Badge tone={planOf(thread) ? 'running' : 'idle'}>{planOf(thread) ? 'Plan' : 'Sender'}</Badge>
    {#if onmarkunread}<OverflowMenu items={[{ label: 'Mark unread', onclick: onmarkunread }]} />{/if}
  </header>
  <div class="chat">
    {#each decisions as item (item.msg_id)}
      {@const type = decisionType(item)}
      {@const isOpen = open(item)}
      {@const answer = sent[item.msg_id]}
      <div class="msg agent wide">
        <span class="who">{who(item)}</span>
        <article class="card" class:target={isOpen && item.msg_id === activeId}>
          <div class="card-head"><h3>{heading(item)}</h3><Badge tone={isOpen ? 'needs-input' : item.state === 'pending' ? 'idle' : 'success'}>{badgeText(item, isOpen)}</Badge></div>
          {#if item.approval}<div class="meta"><Badge tone="needs-input">{item.approval}</Badge></div>{/if}
          {#if bodyText(item)}<Markdown text={bodyText(item)} />{/if}
          {#if item.why?.trim()}<div class="why"><b>WHY</b><Markdown text={item.why} /></div>{/if}
          {#if item.recommendation && !recShownOnOption(item)}<div class="recommendation"><b>RECOMMENDATION</b>{optionLabel(item.recommendation)}{#if item.recommendation.reason}: {item.recommendation.reason}{/if}</div>{/if}
          {#if type === 'question' && item.options?.length}
            <div class="options" role="radiogroup" aria-label={`Options for ${decisionTitle(item)}`}>
              {#each item.options as option, index}
                <label class="opt" class:rec={isRecommended(item, option)} class:chosen={isChosen(item, option)}>
                  <input type="radio" name={`option-${item.msg_id}`} disabled={!isOpen || sending} checked={isChosen(item, option) || (isOpen && item.msg_id === activeId && selectedOption === optionLabel(option))} onchange={() => chooseOption(item, option)} />
                  <span><span class="opt-title"><b>{optionLabel(option)}</b>{#if isRecommended(item, option)}<em class="rec-tag">Recommended</em>{/if}</span>{#if option?.consequence}<small>{option.consequence}</small>{/if}{#if recReason(item, option)}<small class="rec-reason">{recReason(item, option)}</small>{/if}</span>
                </label>
              {/each}
            </div>
          {/if}
          {#if item.notes_text?.trim()}<details class="disclosure"><summary>Notes</summary><Markdown text={item.notes_text} /></details>{/if}
          {#if item.sources?.length}<details class="disclosure"><summary>Sources ({item.sources.length})</summary><ul>{#each item.sources as source}<li>{sourceText(source)}</li>{/each}</ul></details>{/if}
          {#if item.evidence?.length}<Evidence items={item.evidence} urlFor={(index) => `/api/mailbox/${encodeURIComponent(item.msg_id)}/evidence/${index}`} />{/if}
          {#if !isOpen && item.state === 'pending'}
            <div class="inactive"><small class="muted">{staleNote(item)}</small><Button variant="secondary" disabled={sending} onclick={() => ondismiss(item)}>Dismiss</Button></div>
          {/if}
          {#if isOpen && type !== 'info'}<Button variant="secondary" disabled={sending} onclick={() => ondismiss(item)}>Dismiss</Button>{/if}
          {#if isOpen && item.msg_id !== activeId}<Button variant="secondary" onclick={() => onactivate(item.msg_id)}>Answer this</Button>{/if}
          {#if isOpen && type === 'info'}<small class="muted">Information only.</small>{/if}
        </article>
      </div>
      {#if answer}
        <div class="msg me sent-reply"><div class="bubble">{answerLabel(answer.text)}</div><span class="tag">{delivery(item)}</span></div>
      {/if}
    {/each}
  </div>
</div>
{#if active}
  <PinnedBar {placement}>
    <div class="reply">
      {#if decisions.filter((item) => open(item)).length > 1}<small class="target-note">Replying to: {decisionTitle(active)}</small>{/if}
      {#if activeType === 'permission'}
        <div class="actions"><Button disabled={sending} onclick={() => onsend('allow')}>Allow</Button><Button variant="secondary" disabled={sending} onclick={() => onsend('deny')}>Deny</Button></div>
      {:else if activeType === 'approval'}
        <div class="actions"><Button disabled={sending} onclick={() => onsend('approve')}>Approve</Button><Button variant="secondary" disabled={sending} onclick={() => onsend('hold')}>Hold</Button><Button variant="secondary" disabled={sending || !reply.trim()} onclick={() => onsend('ask-more')}>Ask more</Button></div>
        <Textarea id={replyId} label="Reply" placeholder="Note (required for Ask more)" rows={1} bind:value={reply} oninput={noteInput} />
      {:else if activeType === 'info'}
        <Button onclick={() => ondismiss(active)}>Acknowledge</Button>
      {:else}
        <div class="compose">
          <Textarea id={replyId} label="Reply" placeholder="Add a note (optional)" rows={1} bind:value={reply} oninput={noteInput} />
          <Button disabled={sending || (!reply.trim() && !selectedOption)} aria-describedby={!sending && !reply.trim() && !selectedOption ? 'answer-send-reason' : undefined} onclick={() => onsend()}>Send answer</Button>
        </div>
        {#if !sending && !reply.trim() && !selectedOption}<small id="answer-send-reason" class="action-reason">Choose an option or enter a reply to send an answer.</small>{/if}
      {/if}
      {#if status}<span class="entry-status" data-state={entryState} role="status">{status}</span>{/if}
      {#if needsRetry}<Button variant="secondary" onclick={onretry}>Retry</Button>{/if}
    </div>
  </PinnedBar>
{/if}
<style>
  .card-head :global(.badge){flex:none;white-space:nowrap}
  .why{display:grid;gap:var(--space-1)}
  .why b{font-size:var(--font-size-xs);letter-spacing:.08em;color:var(--text-muted)}
  .disclosure{border-top:var(--line) solid var(--border-subtle);padding-top:var(--space-2)}
  .disclosure summary{min-height:var(--control-h);display:flex;align-items:center;color:var(--text-secondary);font-size:var(--font-size-sm);font-weight:650;cursor:pointer}
  .disclosure ul{margin:0;padding-left:var(--space-5);color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .rec-reason{color:var(--text-success)}
  .action-reason{color:var(--text-muted);font-size:var(--font-size-xs)}
  .inactive{display:grid;gap:var(--space-2)}
  .opt-title{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-2)}
  .rec-tag{padding:0 var(--space-2);border-radius:var(--radius-pill);background:var(--text-success);color:var(--surface-1);font-size:var(--font-size-xs);font-style:normal;font-weight:650}
  .thread{display:grid;gap:var(--space-4);min-width:0;padding-bottom:calc(var(--pinned-bar-h, 0px) + var(--space-3))}
  .thread-head{display:flex;align-items:center;gap:var(--space-2)}
  .titles{flex:1;min-width:0}
  h1{margin:0;font-size:var(--font-size-md);color:var(--text-strong);overflow-wrap:anywhere}
  .titles p{margin:0;color:var(--text-muted);font-size:var(--font-size-xs)}
  .chat{display:grid;gap:var(--space-3)}
  .msg{display:grid;gap:var(--space-2);max-width:92%;min-width:0}
  .msg.wide{max-width:100%}
  .who,.tag{color:var(--text-muted);font-size:var(--font-size-xs)}
  .msg.me{justify-self:end;text-align:right}
  .bubble{padding:var(--space-3);border-radius:16px;border-top-right-radius:4px;background:var(--accent);color:var(--text-on-accent);text-align:left;overflow-wrap:anywhere;white-space:pre-wrap}
  .card{display:grid;gap:var(--space-3);min-width:0;padding:var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);box-shadow:var(--elevation-card)}
  .card.target{border-color:var(--accent)}
  .card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-2)}
  h3{margin:0;min-width:0;color:var(--text-strong);font-size:var(--font-size-md);overflow-wrap:anywhere}
  .muted{margin:0;color:var(--text-muted);overflow-wrap:anywhere;white-space:pre-wrap}
  pre{white-space:pre-wrap;overflow-wrap:anywhere}
  .recommendation{padding:var(--space-3);border-radius:9px;background:var(--surface-success);color:var(--text-success);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .recommendation b{display:block;font-size:var(--font-size-xs);letter-spacing:.08em}
  .options{display:grid;gap:var(--space-2)}
  .opt{display:flex;gap:var(--space-3);align-items:flex-start;padding:var(--space-3);min-height:var(--control-h);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-input);cursor:pointer}
  .opt input{flex:none;width:var(--space-5);height:var(--space-5);margin:var(--space-1) 0 0}
  .opt b{display:block;color:var(--text-strong);overflow-wrap:anywhere}
  .opt small{display:block;color:var(--text-muted);overflow-wrap:anywhere}
  .opt.rec{border-color:var(--text-success);background:var(--surface-success)}
  .opt.chosen{background:var(--surface-selected);border-color:var(--accent)}
  .reply{display:grid;gap:var(--space-2);--textarea-max-height:calc(var(--control-h) * 2.25)}
  .compose{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:var(--space-2)}
  .compose :global(textarea){min-width:0}
  .reply :global(label){position:absolute;width:var(--line);height:var(--line);overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
  .actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}
  .target-note,.entry-status{color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
</style>
