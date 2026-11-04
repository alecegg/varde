<script lang="ts">
  import type { ChatChip } from './chatChips';

  let { chips, activeId, needsOpen, needsCount: suppliedNeedsCount, onToggleNeeds }: {
    chips: ChatChip[];
    activeId: string;
    needsOpen: boolean;
    needsCount?: number;
    onToggleNeeds: () => void;
  } = $props();

  let previousNeedsCount: number | undefined;
  let countChanged = $state(false);
  const needsCount = $derived(suppliedNeedsCount ?? chips.reduce((total, chip) => total + chip.needsYou, 0));

  $effect.pre(() => {
    countChanged = previousNeedsCount !== undefined && previousNeedsCount !== needsCount;
    previousNeedsCount = needsCount;
  });
</script>

<nav class="avatars" aria-label="Conversations">
  <button
    class="chip needs-chip"
    class:active={needsOpen}
    class:is-empty={needsCount === 0}
    type="button"
    aria-label={`Show ${needsCount} items needing you`}
    aria-pressed={needsOpen}
    data-needs-chip
    onclick={onToggleNeeds}
  >
    <span class="circle">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
      </svg>
      {#if needsCount > 0}
        <span class="count" class:count-pop={countChanged}>{needsCount}</span>
      {/if}
    </span>
    <span class="label">Needs action</span>
  </button>

  {#each chips as chip (chip.id)}
    <a class="chip person" class:active={chip.id === activeId} href={chip.href} aria-label={chip.label}>
      <span class={`circle ${chip.hue} ${chip.dot ?? ''}`}>
        <span class="initials">{chip.initials}</span>
      </span>
      <span class="label">{chip.label}</span>
    </a>
  {/each}
</nav>

<style>
  .avatars{display:flex;flex-wrap:nowrap;align-items:flex-start;gap:8px;padding:12px 16px 10px;overflow-x:auto;scrollbar-width:none;background:var(--cf-panel);border-bottom:1px solid var(--cf-line)}
  .avatars::-webkit-scrollbar{display:none}
  .chip{position:relative;box-sizing:border-box;width:64px;height:84px;min-width:64px;flex:0 0 64px;display:grid;grid-template-rows:52px 16px;align-content:start;justify-items:center;gap:6px;padding:0;overflow:visible;border:0;background:transparent;text-decoration:none;color:var(--cf-muted);font-size:12px;font-weight:600;line-height:16px;text-align:center;white-space:nowrap}
  .circle{position:relative;box-sizing:border-box;width:52px;height:52px;display:grid;place-items:center;overflow:visible;border-radius:50%;flex:none}
  .label{display:block;width:64px;max-width:64px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center;font-size:12px;font-weight:600;line-height:16px;text-transform:capitalize}
  .needs-chip{cursor:pointer;border-radius:999px;color:var(--cf-muted)}
  .needs-chip .label{text-transform:none}
  .needs-chip .circle{background:var(--cf-accent-bg);color:var(--cf-accent-ink)}
  .needs-chip.is-empty{color:var(--cf-muted)}
  .needs-chip.is-empty .circle{background:var(--cf-soft);color:var(--cf-muted)}
  .needs-chip.active .circle{outline:2px solid var(--cf-text);outline-offset:2px}
  .needs-chip svg{width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
  .count{position:absolute;right:0;top:0;width:20px;height:20px;display:grid;place-items:center;border-radius:50%;background:var(--cf-badge);color:var(--cf-badge-ink);font-size:12px;font-weight:700;line-height:1}
  .count-pop{animation:pop 200ms ease-out}
  .person{color:var(--cf-muted)}
  .person.active{color:var(--cf-text);font-weight:700}
  .person .circle{color:#fff;font-size:15px;font-weight:700}
  .person.active .circle{outline:2px solid var(--cf-text);outline-offset:2px}
  .initials{color:var(--cf-badge-ink);font-size:15px;font-weight:700}
  .violet{background:var(--cf-avatar-violet)}
  .blue{background:var(--cf-avatar-blue)}
  .green{background:var(--cf-avatar-green)}
  .orange{background:var(--cf-avatar-orange)}
  .pink{background:var(--cf-avatar-pink)}
  .circle.running::after,.circle.queued::after,.circle.needs-you::after{content:"";position:absolute;right:0;bottom:0;width:14px;height:14px;border:2px solid var(--cf-panel);border-radius:50%}
  .circle.running::after{background:#16834b}
  .circle.queued::after{background:#b36c00}
  .circle.needs-you::after{background:var(--cf-accent)}
</style>
