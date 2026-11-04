<script lang="ts">
 import Input from './Input.svelte';
 let { value = $bindable(''), 'aria-label': ariaLabel, placeholder, name }: { value?: string; 'aria-label': string; placeholder?: string; name?: string } = $props();
</script>
<Input type="search" aria-label={ariaLabel} {placeholder} {name} bind:value/>
