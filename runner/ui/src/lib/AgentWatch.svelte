<script lang="ts">
  import { onMount } from 'svelte';
  import { Badge, Stack } from './ui';
  import {
    agentWatchUrl,
    MAX_WATCH_EVENTS,
    type AgentWatchEvent,
    type AgentWatchSnapshot,
  } from './agentWatch';

  let { agentId }: { agentId: string } = $props();
  let snapshot = $state<AgentWatchSnapshot | null>(null);
  let events = $state<AgentWatchEvent[]>([]);
  let lastSeq = $state<number | null>(null);
  let source: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  let consecutiveFailures = 0;

  const MAX_CONSECUTIVE_FAILURES = 5;
  const RETRY_BASE_MS = 1000;
  const RETRY_MAX_MS = 8000;

  function parseFrame(data: string): Record<string, unknown> | null {
    try {
      const value: unknown = JSON.parse(data);
      return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
    } catch {
      return null;
    }
  }

  function fail() {
    if (retryTimer !== null) clearTimeout(retryTimer);
    retryTimer = null;
    source?.close();
    source = null;
  }

  function connect() {
    if (closed || typeof EventSource === 'undefined') return;
    const current = new EventSource(agentWatchUrl(agentId, lastSeq));
    source = current;
    current.addEventListener('snapshot', (event) => {
      const frame = parseFrame((event as MessageEvent<string>).data);
      if (!frame || typeof frame.last_seq !== 'number' || !Array.isArray(frame.events)) {
        fail();
        return;
      }
      snapshot = frame as unknown as AgentWatchSnapshot;
      // The server sends deltas after a valid `after` cursor, but sends a full
      // snapshot when the cursor is invalid or the event window overflows.
      // A snapshot is therefore a replacement window, not an append.
      events = snapshot.events.slice(-MAX_WATCH_EVENTS);
      lastSeq = snapshot.last_seq;
      consecutiveFailures = 0;
    });
    current.addEventListener('event', (event) => {
      const frame = parseFrame((event as MessageEvent<string>).data);
      if (!frame || typeof frame.seq !== 'number' || typeof frame.kind !== 'string') {
        fail();
        return;
      }
      if (lastSeq !== null && frame.seq <= lastSeq) return;
      const next = frame as unknown as AgentWatchEvent;
      events = [...events.slice(-(MAX_WATCH_EVENTS - 1)), next];
      lastSeq = next.seq;
      consecutiveFailures = 0;
    });
    current.addEventListener('error', (event) => {
      const data = 'data' in event && typeof event.data === 'string' ? event.data : '';
      if (data) {
        fail();
        return;
      }
      current.close();
      if (source === current) source = null;
      consecutiveFailures += 1;
      if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        return;
      }
      const delay = Math.min(
        RETRY_BASE_MS * 2 ** (consecutiveFailures - 1),
        RETRY_MAX_MS,
      );
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, delay);
    });
  }

  onMount(() => {
    connect();
    return () => {
      closed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      source?.close();
      source = null;
    };
  });
</script>

<section class="watch" aria-label="Agent watch">
  {#if snapshot}
    <div class="snapshot">
      <strong>Snapshot · sequence {snapshot.last_seq}</strong>
      <span>{snapshot.open_intents?.length ?? 0} open intents</span>
      <span>{snapshot.pending_waits?.length ?? 0} pending waits</span>
      {#if snapshot.truncated}<span>Earlier events are omitted.</span>{/if}
    </div>
  {/if}
  {#if events.length}
    <Stack gap="2">
      {#each events as item (item.seq)}
        <article class="event">
          <div class="event-heading"><Badge tone="neutral">{item.kind}</Badge><span>Sequence {item.seq}</span></div>
          <pre>{JSON.stringify(item.payload, null, 2)}</pre>
        </article>
      {/each}
    </Stack>
  {:else if snapshot}
    <p class="empty">No events in this snapshot.</p>
  {/if}
</section>

<style>
  .watch{display:grid;gap:var(--space-3);min-width:0}
  .empty{margin:0;color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .snapshot{display:flex;flex-wrap:wrap;gap:var(--space-2);color:var(--text-body);font-size:var(--font-size-sm)}
  .snapshot strong{flex-basis:100%;color:var(--text-strong)}
  .event{min-width:0;padding:var(--space-2);border:var(--line) solid var(--border-subtle);border-radius:var(--radius-control)}
  .event-heading{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2);color:var(--text-muted);font-size:var(--font-size-xs)}
  pre{max-width:100%;margin:var(--space-2) 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:var(--font-mono);font-size:var(--font-size-sm)}
</style>
