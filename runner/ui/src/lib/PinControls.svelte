<script lang="ts">
  import Button from './ui/Button.svelte';
  import DragHandle from './DragHandle.svelte';
  import type { PinTarget } from './agentPins';

  let { pinned, index, total, onpin, onmove, onreorder }: {
    pinned: boolean;
    index: number;
    total: number;
    onpin: () => void;
    onmove: (delta: number) => void;
    onreorder: (target: PinTarget) => void;
  } = $props();

  const lonelyHint = 'No other pinned agent in this state';
  const earlierHint = $derived(total < 2 ? lonelyHint : 'Already first among its pinned neighbors');
  const laterHint = $derived(total < 2 ? lonelyHint : 'Already last among its pinned neighbors');
</script>

<div class="pin-controls" aria-label="Agent order controls">
  <Button variant="ghost" class="control" aria-label={pinned ? 'Unpin agent' : 'Pin agent'} aria-pressed={pinned} title={pinned ? 'Unpin agent' : 'Pin agent to the top'} onclick={onpin}>{pinned ? '★' : '☆'}</Button>
  {#if pinned}
    <span class="hint" title={index === 0 ? earlierHint : undefined}><Button variant="ghost" class="control" aria-label="Move agent earlier" disabled={index === 0} onclick={() => onmove(-1)}>↑</Button></span>
    <span class="hint" title={index === total - 1 ? laterHint : undefined}><Button variant="ghost" class="control" aria-label="Move agent later" disabled={index === total - 1} onclick={() => onmove(1)}>↓</Button></span>
    <DragHandle {index} onreorder={onreorder} />
  {/if}
</div>

<style>
  .pin-controls{display:flex;align-items:center;gap:var(--space-1);flex:none}:global(.ui-button.control){width:44px;height:44px;min-width:44px;min-height:44px;padding:0;font-size:1.1rem}.hint{display:inline-flex}
</style>
