<script lang="ts">
  import { onMount } from 'svelte';
  import SettingsNav from './SettingsNav.svelte';
  import { settingsSections } from './settingsNav';
  import ChatHeader from '../../lib/ChatHeader.svelte';
  onMount(() => {
    const section = settingsSections.find((item) => item.id === window.location.hash.slice(1));
    if (section) window.location.replace('/settings/' + section.id);
  });
</script>
<svelte:head><title>Varde Runner · Settings</title><meta name="description" content="Configure Varde Runner settings." /></svelte:head>
<div class="settings-overview">
  <ChatHeader title="Settings" subtitle="Configure your workspace" backHref="/chat" />
  <div class="settings-nav-content"><SettingsNav /></div>
</div>
<style>
  .settings-overview{display:grid;gap:24px;min-width:0}.settings-nav-content{padding:0 16px 16px}
</style>
