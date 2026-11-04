<script lang="ts">
  import ChatHeader from '../../../lib/ChatHeader.svelte';
  import Harnesses from '../sections/harnesses.svelte';
  import Runner from '../sections/runner.svelte';
  import RoleTypes from '../sections/role-types.svelte';
  import ModelTypes from '../sections/model-types.svelte';
  import Display from '../sections/display.svelte';
  import Review from '../sections/review.svelte';
  import Status from '../sections/status.svelte';
  let { data }: { data: { section: { id: keyof typeof sectionComponents; label: string; summary: string } | null } } = $props();
  const sectionComponents = { harnesses: Harnesses, runner: Runner, 'role-types': RoleTypes, 'model-types': ModelTypes, display: Display, review: Review, status: Status };
</script>
{#if data.section}
  {@const SectionContent = sectionComponents[data.section.id as keyof typeof sectionComponents]}
  <div class="settings-section"><ChatHeader title={data.section.label} subtitle={data.section.summary} backHref="/settings" backLabel="Back to settings" /><div class="settings-content" class:unframed={['display', 'review', 'status'].includes(data.section.id)}><SectionContent /></div></div>
{/if}
<style>
  .settings-section{display:grid;gap:16px;min-width:0}.settings-content{min-width:0;padding:0 16px 16px}
  .settings-section :global(input:not([type='checkbox']):not([type='radio'])),
  .settings-section :global(select),
  .settings-section :global(textarea){box-sizing:border-box;width:min(100%,32rem);min-height:max(44px,var(--control-h));max-width:100%}
  .settings-section :global(textarea){min-height:128px;max-height:160px;resize:none}
  .settings-section :global(select){font-size:var(--font-size-md)}
  .settings-section :global(.ui-button){box-sizing:border-box;min-width:44px;min-height:max(44px,var(--control-h));max-width:100%}
  .settings-content.unframed :global(.section){padding:0;border:0;border-radius:0;background:transparent}
</style>
