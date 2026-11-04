<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import ThreadView from './ThreadView.svelte';
  import { threadDecisions, type Item, type Thread } from './thread';

  type Sent = { text: string; sent_at: string };
  let { thread, decisions, openIds, sent = {}, onupdated = () => {}, onback, onmarkunread, placement = 'fixed', messageOrder = 'oldest-first', showTitle = true }: {
    thread: Thread;
    decisions: Item[];
    openIds: string[];
    sent?: Record<string, Sent | null>;
    onupdated?: () => void | Promise<void>;
    onback?: () => void;
    onmarkunread?: () => void;
    placement?: 'fixed' | 'inline';
    messageOrder?: 'oldest-first' | 'newest-first';
    showTitle?: boolean;
  } = $props();

  let selectedOption = $state(''), reply = $state(''), sending = $state(false);
  let entryState = $state('draft'), error = $state('');
  let localSent = $state<Record<string, Sent | null>>({});
  let transientKeys: Record<string, string> = {};
  onMount(() => {
    const restored: Record<string, Sent | null> = {};
    for (const item of decisions) {
      try { restored[item.msg_id] = JSON.parse(localStorage.getItem(`varde:sent:${item.msg_id}`) ?? 'null') as Sent | null; }
      catch { restored[item.msg_id] = null; }
    }
    localSent = { ...localSent, ...restored };
  });
  $effect(() => { const external = sent; localSent = { ...untrack(() => localSent), ...external }; });
  let chosenId = $state('');
  let draftDecisionId: string | undefined;
  const chronological = $derived(threadDecisions(thread, new Map(decisions.map((item) => [item.msg_id, item]))));
  const ordered = $derived(messageOrder === 'newest-first' ? [...chronological].reverse() : chronological);
  const openDecisions = $derived(ordered.filter((item) => item.mailbox_open !== false && openIds.includes(item.msg_id)));
  const defaultOpen = $derived(messageOrder === 'newest-first' ? openDecisions[0] : openDecisions.at(-1));
  const activeId = $derived(openDecisions.find((item) => item.msg_id === chosenId)?.msg_id ?? defaultOpen?.msg_id ?? '');
  const draftKey = (id: string) => `varde:reply:${id}`;
  function readDraft(id: string) {
    try { return JSON.parse(localStorage.getItem(draftKey(id)) ?? 'null') as { key?: string; text?: string } | null; }
    catch { return null; }
  }
  $effect(() => {
    const id = activeId;
    if (id === draftDecisionId) return;
    draftDecisionId = id;
    selectedOption = '';
    reply = id ? readDraft(id)?.text ?? '' : '';
    entryState = id && untrack(() => localSent[id]) ? 'delivered' : 'draft';
    error = '';
  });
  function updateReply(value: string) {
    const id = activeId;
    if (!id) return;
    const key = draftKey(id), previous = readDraft(id);
    if (value) {
      const draft = { key: previous?.key ?? transientKeys[id] ?? crypto.randomUUID(), text: value };
      transientKeys[id] = draft.key;
      try { localStorage.setItem(key, JSON.stringify(draft)); } catch { /* Sending remains available without draft storage. */ }
    } else {
      delete transientKeys[id];
      try { localStorage.removeItem(key); } catch { /* Draft storage is best effort. */ }
    }
  }
  async function send(option?: string) {
    const id = activeId, item = ordered.find((decision) => decision.msg_id === id);
    const chosen = option ?? selectedOption, text = reply;
    if (!item || (!text.trim() && !chosen)) return;
    sending = true; entryState = 'sending'; error = '';
    try {
      const key = readDraft(id)?.key ?? transientKeys[id] ?? crypto.randomUUID();
      transientKeys[id] = key;
      try { localStorage.setItem(draftKey(id), JSON.stringify({ key, text })); } catch { /* Server send is authoritative. */ }
      const body = { option: chosen || undefined, text: item.kind === 'permission' ? '' : text, idempotency_key: key };
      const response = await fetch(`/api/mailbox/${encodeURIComponent(id)}/answer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`Send failed (${response.status})`);
      const result = await response.json();
      entryState = result.status;
      if (result.status === 'delivered') {
        const answer = { text: result.reply ?? (chosen || text), sent_at: result.sent_at };
        try { localStorage.setItem(`varde:sent:${id}`, JSON.stringify(answer)); } catch { /* Server state remains authoritative. */ }
        try { localStorage.removeItem(draftKey(id)); } catch { /* Sent state is kept in memory and on the server. */ }
        delete transientKeys[id];
        localSent = { ...localSent, [id]: answer };
        reply = ''; selectedOption = '';
      }
      await onupdated();
    } catch (e) {
      entryState = 'failed'; error = e instanceof Error ? e.message : 'Could not send reply';
    } finally { sending = false; }
  }
  async function retry() {
    if (entryState === 'failed') return send();
    const key = readDraft(activeId)?.key ?? transientKeys[activeId];
    if (!key) return;
    sending = true;
    try {
      const response = await fetch(`/entries/${key}/retry`, { method: 'POST' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? 'Retry failed');
      entryState = result.status;
    } catch (e) { entryState = 'failed'; error = e instanceof Error ? e.message : 'Retry failed'; }
    finally { sending = false; }
  }
  async function dismiss(item: Item) {
    sending = true; error = '';
    try {
      const response = await fetch(`/api/mailbox/${encodeURIComponent(item.msg_id)}/dismiss`, { method: 'POST' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? 'dismiss failed');
      await onupdated();
    } catch (e) { error = e instanceof Error ? e.message : 'dismiss failed'; }
    finally { sending = false; }
  }
</script>
<ThreadView
  {thread}
  decisions={ordered}
  {openIds}
  sent={localSent}
  {activeId}
  bind:selectedOption
  bind:reply
  {entryState}
  {error}
  {sending}
  {onback}
  {placement}
  {showTitle}
  onactivate={(id) => chosenId = id}
  onsend={send}
  onretry={retry}
  ondismiss={dismiss}
  onmarkunread={onmarkunread}
  onreply={updateReply}
/>
