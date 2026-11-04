<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import { keyboardSafe } from './keyboard';
  let { children, placement = 'fixed' }: { children: Snippet; placement?: 'fixed' | 'inline' | 'inline-desktop' } = $props();
  let bar: HTMLDivElement;
  onMount(() => {
    if (placement === 'inline') return;
    const root = document.documentElement;
    const tabs = document.querySelector('.tab-bar'); // The tab bar's real height, not the --tab-bar-h estimate.
    const observer = new ResizeObserver(() => {
      root.style.setProperty('--pinned-bar-h', `${bar.getBoundingClientRect().height}px`);
      if (tabs) bar.style.setProperty('--pinned-offset', `${tabs.getBoundingClientRect().height}px`);
    });
    observer.observe(bar);
    if (tabs) observer.observe(tabs);
    return () => { observer.disconnect(); root.style.removeProperty('--pinned-bar-h'); };
  });
</script>
<div bind:this={bar} class="pinned-bar" class:inline-all={placement === 'inline'} class:inline-desktop={placement === 'inline-desktop'} use:keyboardSafe>{@render children()}</div>
<style>
  .pinned-bar{position:fixed;left:var(--nav-width,0px);right:0;bottom:max(var(--keyboard-inset,0px),var(--pinned-offset,var(--tab-bar-h,0px)));padding:var(--space-2);padding-bottom:max(var(--space-2),env(safe-area-inset-bottom));background:var(--surface-1);border-top:var(--line) solid var(--border);z-index:var(--layer-menu)}
  .pinned-bar.inline-all{position:static;left:auto;right:auto;bottom:auto;flex:0 0 auto;padding:0;background:transparent;border-top:0;z-index:auto}
  @media(min-width:900px){.pinned-bar.inline-desktop{position:static;left:auto;right:auto;bottom:auto;flex:0 0 auto}}
</style>
