<script lang="ts">
  import type { PinTarget } from './agentPins';

  let { index, onreorder }: { index: number; onreorder: (target: PinTarget) => void } = $props();
  let pointerId: number | null = $state(null);
  let target = $state<PinTarget | null>(null);

  function findTarget(event: PointerEvent): PinTarget | null {
    const element = document.elementFromPoint(event.clientX, event.clientY);
    const row = element?.closest<HTMLElement>('[data-agent-index]');
    const parsed = Number(row?.dataset.agentIndex);
    if (!Number.isInteger(parsed) || parsed < 0) return null;
    return { index: parsed, group: row?.dataset.pinGroup ?? '' };
  }

  function start(event: PointerEvent) {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
    const handle = event.currentTarget;
    if (!(handle instanceof HTMLButtonElement)) return;
    const row = handle.closest<HTMLElement>('[data-agent-index]');
    pointerId = event.pointerId;
    target = { index, group: row?.dataset.pinGroup ?? '' };
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function move(event: PointerEvent) {
    if (event.pointerId !== pointerId) return;
    target = findTarget(event);
  }

  function finish(event: PointerEvent) {
    if (event.pointerId !== pointerId) return;
    const dropTarget = findTarget(event) ?? target;
    pointerId = null;
    target = null;
    if (dropTarget !== null && dropTarget.index !== index) onreorder(dropTarget);
  }

  function cancel(event: PointerEvent) {
    if (event.pointerId !== pointerId) return;
    pointerId = null;
    target = null;
  }
</script>

<button
  type="button"
  class="drag-handle"
  aria-hidden="true"
  tabindex="-1"
  aria-label="Drag to reorder"
  title="Drag to reorder"
  data-drag-target={target?.index ?? undefined}
  onpointerdown={start}
  onpointermove={move}
  onpointerup={finish}
  onpointercancel={cancel}
>
  <svg aria-hidden="true" viewBox="0 0 20 24" focusable="false">
    <path d="M4 4h3M13 4h3M4 12h3M13 12h3M4 20h3M13 20h3" />
  </svg>
</button>

<style>
  .drag-handle {
    min-width: var(--control-h);
    min-height: var(--control-h);
    display: grid;
    place-items: center;
    padding: 0;
    border: var(--line) solid var(--border-control);
    border-radius: var(--radius-control);
    background: var(--surface-1);
    color: var(--text-body);
    cursor: grab;
    touch-action: none;
  }

  svg { width: 20px; height: 24px; fill: none; stroke: currentColor; stroke-width: 2.5; stroke-linecap: round; }

  .drag-handle:active {
    cursor: grabbing;
  }

  .drag-handle:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }
</style>
