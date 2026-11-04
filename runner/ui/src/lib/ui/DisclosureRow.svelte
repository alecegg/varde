<script lang="ts">
 import type { Snippet } from 'svelte';
 let {title,summary,ariaLabel,open=$bindable(false),id,children,onToggle}:{title?:string;summary?:Snippet;ariaLabel?:string;open?:boolean;id:string;children:Snippet;onToggle?:(open:boolean)=>void}=$props();
 let trigger:HTMLButtonElement;
 function toggle(){open=!open;onToggle?.(open)}
 function close(){open=false;onToggle?.(false);trigger?.focus()}
</script>
<section class="row"><button bind:this={trigger} data-ui-control type="button" aria-label={ariaLabel} aria-expanded={open} aria-controls={id} onclick={toggle}>{#if summary}{@render summary()}{:else}<span>{title}</span>{/if}<span aria-hidden="true">{open?'⌄':'›'}</span></button><div {id} class="detail" hidden={!open}>{@render children()}<button type="button" data-ui-control class="close" onclick={close}>Close</button></div></section>
<style>.row{border-bottom:var(--line) solid var(--border-subtle)}.row>button{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:var(--control-h);padding:0 var(--space-3);border:0;background:transparent;color:var(--text-strong);font:inherit;font-weight:650;text-align:left;touch-action:manipulation}.detail{padding:var(--space-3);color:var(--text-secondary)}.detail[hidden]{display:none}.close{min-height:var(--control-h);padding:0 var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-1);color:var(--text-body);touch-action:manipulation}</style>
