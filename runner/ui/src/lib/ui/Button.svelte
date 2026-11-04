<script lang="ts">
 import type { HTMLAttributes } from 'svelte/elements';
 let {variant='primary',size='md',href,type='button',disabled=false,class:className='',children,...rest}: HTMLAttributes<HTMLElement> & {variant?:'primary'|'secondary'|'ghost'|'danger'|'link';size?:'sm'|'md'|'lg';href?:string;type?:'button'|'submit'|'reset';disabled?:boolean;children:import('svelte').Snippet}=$props();
 const level=$derived(variant==='primary'?'primary':variant==='ghost'||variant==='link'?'tertiary':'secondary');
</script>
{#if href}<a {href} data-variant={level} class={`ui-button ${variant} ${size} ${className}`} {...rest}>{@render children()}</a>{:else}<button {type} {disabled} data-variant={level} class={`ui-button ${variant} ${size} ${className}`} {...rest}>{@render children()}</button>{/if}
<style>
.ui-button{min-width:var(--control-h);display:inline-flex;align-items:center;justify-content:center;min-height:var(--control-h);padding:0 var(--space-4);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);font-size:var(--font-size-sm);font-weight:650;text-decoration:none;cursor:pointer;touch-action:manipulation}.ui-button.primary{background:var(--accent);border-color:var(--accent);color:var(--text-on-accent)}.ui-button.ghost,.ui-button.link{background:transparent;border-color:transparent}.ui-button.link{color:var(--accent)}.ui-button{gap:var(--space-2)}.ui-button.danger{color:var(--text-danger)}.ui-button.sm{padding-inline:var(--space-3)}.ui-button.lg{padding-inline:var(--space-5)}.ui-button[hidden]{display:none}.ui-button:disabled,.ui-button.primary:disabled{opacity:1;background:var(--surface-disabled);border:2px solid var(--border-strong);color:var(--text-strong);cursor:not-allowed}.ui-button:focus-visible{outline:var(--ring-width) solid var(--focus);outline-offset:var(--ring-width)}
.ui-button.primary:focus-visible{outline-color:var(--text-on-accent)}
</style>
