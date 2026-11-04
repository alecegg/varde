<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { effectiveConfig } from '../../../lib/agentConfig';
  import { listIdentities, type Identity } from '../../../lib/identitiesApi';
  import { profileHue, profileInitials, profileRows, profileState } from '../../../lib/chat/profileRows';
  import ChatHeader from '../../../lib/ChatHeader.svelte';
  import type { Role, ModelType } from '../../roles/roles';

  let identity = $state<Identity | null>(null);
  let roles = $state<Record<string, Role>>({});
  let types = $state<Record<string, ModelType>>({});
  let loading = $state(true);
  let error = $state('');
  const agentId = $derived(page.params.agentId ?? '');
  const avatarText = $derived(profileInitials(identity));
  const avatarColor = $derived(profileHue(identity));
  const roleConfig = $derived(effectiveConfig(identity?.role, roles, types));
  const details = $derived(profileRows(identity, roleConfig ? {
    harness: roleConfig.harness,
    model: roleConfig.model,
    reasoning_effort: roleConfig.effort,
  } : null));
  const profileStatus = $derived(profileState(identity));

  async function load() {
    loading = true;
    error = '';
    try {
      const identities = await listIdentities();
      identity = identities.find((item) => item.id === agentId) ?? null;
      if (!identity) return;
      const response = await fetch('/api/roles', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? `Could not load roles (${response.status})`);
      roles = data.roles ?? {};
      types = data.types ?? {};
    } catch {
      error = 'Could not load this profile. Check your connection and retry.';
    } finally {
      loading = false;
    }
  }

  onMount(() => { void load(); });
</script>

<svelte:head><title>{identity?.name ?? 'Agent profile'} · Varde Runner</title></svelte:head>
<section class="profile-screen" data-profile={agentId}>
  <ChatHeader title="Agent profile" subtitle={identity?.name ?? 'Agent details'} backHref={`/thread/${encodeURIComponent(agentId)}`} backLabel="Back to conversation" />
  {#if loading}
    <p class="message" role="status">Loading profile…</p>
  {:else if error}
    <p class="message error" role="alert">{error}</p>
  {:else if identity}
    {#if identity.error}<p class="message error" role="status">{identity.error}</p>{/if}
    <div class="profile">
      <span class={`avatar ${avatarColor} ${profileStatus.label}`} aria-hidden="true">{avatarText}</span>
      <span><h2>{identity.name || identity.label || identity.id}</h2><p><span class="state">{profileStatus.label}</span></p></span>
    </div>
    <section class="card config-card" aria-label="Read-only configuration">
        {#each details as row (row.label)}
          <div class="row"><span>{row.label}</span><strong>{row.value}</strong></div>
        {/each}
    </section>
    <a class="btn profile-return" href={`/thread/${encodeURIComponent(agentId)}`}>Back to conversation</a>
  {:else}
    <section class="empty-state"><h1>Profile unavailable</h1><p>This agent could not be found.</p><div class="empty-actions"><a class="btn" href={`/thread/${encodeURIComponent(agentId)}`}>Back to conversation</a><button class="btn" type="button" onclick={() => void load()}>Retry</button></div></section>
  {/if}
</section>

<style>
  .profile-screen{margin:-16px;padding:0 16px calc(16px + 24px);color:var(--cf-text);font-family:system-ui,-apple-system,sans-serif;font-size:17px;line-height:1.4}
  .profile{display:flex;align-items:center;gap:16px;margin:16px 0 24px}
  .avatar{position:relative;width:72px;height:72px;display:grid;place-items:center;border:0;border-radius:50%;color:#fff;font-size:19px;font-weight:700;flex:none}
  .avatar.violet{background:var(--cf-avatar-violet)}.avatar.blue{background:var(--cf-avatar-blue)}.avatar.green{background:var(--cf-avatar-green)}.avatar.orange{background:var(--cf-avatar-orange)}.avatar.pink{background:var(--cf-avatar-pink)}
  .avatar.running:after,.avatar.queued:after,.avatar.needs-you:after{content:"";position:absolute;width:14px;height:14px;right:0;bottom:0;border:2px solid var(--cf-panel);border-radius:50%}
  .avatar.running:after{background:#16834b}.avatar.queued:after{background:#b36c00}.avatar.needs-you:after{background:var(--cf-accent)}
  h2{margin:0;font-size:23px;letter-spacing:-.02em}.profile p{margin:4px 0;color:var(--cf-muted);font-size:14px}
  .state{display:inline-block;padding:5px 11px;border-radius:999px;background:var(--cf-goodbg);color:var(--cf-good);font-weight:700}
  .card{padding:16px;border:0;border-radius:20px;background:var(--cf-panel);box-shadow:var(--cf-shadow)}
  .config-card{padding:16px}.row{display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:52px;border-bottom:1px solid var(--cf-line);font-size:15px}.row:last-child{border-bottom:0}.row span{color:var(--cf-muted)}.row strong{font-size:15px;font-weight:600}
  .btn{height:48px;display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;padding:0 18px;border:0;border-radius:999px;background:var(--cf-soft);color:var(--cf-text);font-size:15px;font-weight:650;text-decoration:none}.profile-return{margin-top:16px}
  .message,.empty-state{margin:0;padding:20px;border-radius:20px;background:var(--cf-panel)}.error{color:var(--cf-bad)}.empty-state p{color:var(--cf-muted)}.empty-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}.empty-actions button{cursor:pointer;font-family:inherit}
</style>
