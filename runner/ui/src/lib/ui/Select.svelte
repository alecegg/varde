<script lang="ts">
 import type { HTMLSelectAttributes } from 'svelte/elements';
 let {label,id,value=$bindable(''),options,hint,error,...rest}:HTMLSelectAttributes & {label?:string;id?:string;value?:string;options:{value:string;label:string}[];hint?:string;error?:string}=$props();
 const generatedId=$props.id(); let fieldId=$derived(id??generatedId); let descriptionId=$derived(`${fieldId}-description`);
</script>
{#if label}<label for={fieldId}>{label}</label>{/if}<select id={fieldId} bind:value aria-invalid={error?true:undefined} aria-describedby={hint||error?descriptionId:undefined} {...rest}>{#each options as option}<option value={option.value}>{option.label}</option>{/each}</select>{#if hint||error}<small id={descriptionId} class:error>{error??hint}</small>{/if}
<style>label{display:block;margin-bottom:var(--space-1);color:var(--text-secondary);font-weight:650}select{box-sizing:border-box;width:100%;height:44px;min-height:44px;padding:0 var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-input);color:var(--text-body);font:inherit;font-size:16px}select:focus-visible{outline:var(--ring-width) solid var(--focus);box-shadow:0 0 0 var(--selected-edge) var(--focus-shadow)}small{display:block;color:var(--text-muted)}small.error{color:var(--text-danger)}</style>
