<script lang="ts">
  import { BACK_BUTTON_SIZE } from './backButtonGeometry';
  let { href, label = 'Back', onclick }: { href?: string; label?: string; onclick?: () => void } = $props();
</script>

{#if href}
<a class="back-button" {href} aria-label={label} title={label} style={`--back-button-size: ${BACK_BUTTON_SIZE}px`}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15.5 5-7 7 7 7" /></svg>
</a>
{:else}
<button class="back-button" type="button" aria-label={label} title={label} {onclick} style={`--back-button-size: ${BACK_BUTTON_SIZE}px`}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15.5 5-7 7 7 7" /></svg>
</button>
{/if}

<style>
  .back-button{display:grid;place-items:center;box-sizing:border-box;flex:none;width:var(--back-button-size);height:var(--back-button-size);padding:0;border:1px solid var(--cf-line);border-radius:50%;background:var(--cf-soft);color:var(--cf-text);text-decoration:none;cursor:pointer}
  .back-button svg{display:block;width:var(--icon-size);height:var(--icon-size);fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  .back-button:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
</style>
