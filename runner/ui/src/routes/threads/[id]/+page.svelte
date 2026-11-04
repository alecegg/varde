<script lang="ts">
  import { page } from '$app/state';
  import { loadThreads, normalizeThreadMail, threadForRoute, threadName, type ThreadMail } from '../../../lib/mail/thread';
  import { permissionTitle } from '../../../lib/chat/conversationRows';
  import ThreadPanel from '../../../lib/mail/ThreadPanel.svelte';
  import ChatHeader from '../../../lib/ChatHeader.svelte';
  import { Card } from '../../../lib/ui';
  import Skeleton from '../../../lib/ui/Skeleton.svelte';
  import { cacheRead, cacheWrite } from '../../../lib/cache';

  let mail = $state<ThreadMail | null>(null);
  let error = $state('');
  let loading = $state(true);
  const routeId = $derived(page.params.id ?? '');
  async function load(routeId: string) {
    const key = `varde:cache:mail-thread:${encodeURIComponent(routeId)}:v1`;
    if (!mail) {
      const cached = normalizeThreadMail(cacheRead<ThreadMail | null>(key, 10 * 60 * 1000));
      if (cached) { mail = cached; loading = false; }
    }
    try {
      const found = threadForRoute(await loadThreads(), routeId) ?? null;
      if (page.params.id !== routeId) return;
      mail = found;
      cacheWrite(key, found);
      error = mail ? '' : 'Conversation not found.';
    } catch (cause) { if (page.params.id === routeId) error = cause instanceof Error ? cause.message : 'Could not load conversation'; }
    finally { if (page.params.id === routeId) loading = false; }
  }
  $effect(() => { void load(routeId); });
</script>

<svelte:head><title>Varde Runner · Conversation</title></svelte:head>
<div class="page">
  <ChatHeader title={mail?.thread.thread_id.startsWith('plan:') ? 'Plan' : mail ? threadName(mail.thread) : 'Conversation'} subtitle={mail ? mail.thread.thread_id.startsWith('plan:') ? 'Plan conversation' : permissionTitle(mail.thread.sender, mail.thread.title, threadName(mail.thread)) : error || (loading ? '' : 'Conversation details')} />
  {#if error}<Card><p role="alert">{error}</p></Card>
  {:else if mail}
    {#if mail.decisions.length}<ThreadPanel {...mail} placement="inline" onupdated={() => load(routeId)} />
    {:else}<Card><p class="empty-thread">{mail.thread.last_preview || mail.thread.title || 'No messages in this conversation yet.'}</p></Card>{/if}
  {:else if loading}<div aria-busy="true"><Skeleton rows={4} card /></div>{/if}
</div>

<style>.page{display:grid;gap:var(--space-4);min-width:0}</style>
