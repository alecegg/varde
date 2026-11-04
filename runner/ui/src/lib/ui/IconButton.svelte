<script lang="ts">
 import type { HTMLButtonAttributes } from 'svelte/elements';
 let {label,variant='ghost',class:className='',children,...rest}:HTMLButtonAttributes & {label:string;variant?:'primary'|'secondary'|'ghost'|'danger';children:import('svelte').Snippet}=$props();
 const level=$derived(variant==='primary'?'primary':variant==='ghost'?'tertiary':'secondary');
</script>
<button data-variant={level} class={`icon-button ${variant} ${className}`} aria-label={label} title={label} {...rest}>{@render children()}</button>
<style>.icon-button{width:var(--control-h);height:var(--control-h);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);display:inline-flex;align-items:center;justify-content:center;padding:0;cursor:pointer;touch-action:manipulation}.icon-button.ghost{background:transparent;border-color:transparent}.icon-button.primary{background:var(--accent);border-color:var(--accent);color:var(--text-on-accent)}.icon-button:disabled{opacity:.55;cursor:not-allowed}.icon-button.danger{color:var(--text-danger)}.icon-button:focus-visible{outline:var(--ring-width) solid var(--focus);outline-offset:var(--ring-width)}</style>
