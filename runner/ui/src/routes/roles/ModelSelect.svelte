<script lang="ts">
  let { label, ariaLabel, value = $bindable(''), options, onchange, disabled = false }: { label?: string; ariaLabel?: string; value?: string; options: { value: string; label: string; group?: string }[]; onchange?: (event: Event & { currentTarget: HTMLSelectElement }) => void; disabled?: boolean } = $props();
  let fieldId = $props.id();
  let groups = $derived(Object.groupBy(options, (option) => option.group ?? ''));
</script>
{#if label}<label for={fieldId}>{label}</label>{/if}
<select id={fieldId} bind:value {onchange} {disabled} aria-label={ariaLabel ?? label}>
  {#each Object.entries(groups) as [group, items]}
    {#if group}<optgroup label={group}>{#each items ?? [] as option}<option value={option.value}>{option.label}</option>{/each}</optgroup>
    {:else}{#each items ?? [] as option}<option value={option.value}>{option.label}</option>{/each}{/if}
  {/each}
</select>
<style>
  label{display:block;margin-bottom:var(--space-1);color:var(--text-secondary);font-weight:650}
  select{box-sizing:border-box;width:100%;height:var(--control-h);padding:0 var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-input);color:var(--text-body);font-family:inherit;font-size:var(--font-size-md)}
  select:focus-visible{outline:var(--ring-width) solid var(--focus);box-shadow:0 0 0 var(--selected-edge) var(--focus-shadow)}
</style>
