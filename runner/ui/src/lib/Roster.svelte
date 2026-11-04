<script lang="ts">
  import { onMount } from 'svelte';
  import { Badge, Section } from './ui';
  import { listAgents, type Agent } from './agentsApi';
  import { identityInstances, listIdentities, rosterLines, stateLabel, stateTone, type Identity, type IdentityInstance } from './identitiesApi';
  import { rosterCounts } from './rosterCounts';
  import { refreshWhenVisible } from './refresh';
  import { onSnapshot } from './mail/thread';
  import { profileLinkLabels } from './rosterLabel';
  let { listFiltered = false }: { listFiltered?: boolean } = $props();
  let identities: Identity[] = $state([]);
  let agents: Agent[] = $state([]);
  let instances: Record<string, IdentityInstance[]> = $state({});
  let expanded = $state('');
  let error = $state('');
  let linkLabels = $derived(profileLinkLabels(identities));
  let counts = $derived(rosterCounts(agents, identities));
  async function load() {
    try {
      const [loaded, liveAgents] = await Promise.all([listIdentities(), listAgents()]);
      const visible = rosterLines(loaded);
      const visibleIds = new Set(visible.map((identity) => identity.id));
      identities = [...visible, ...loaded.filter((identity) => identity.error && !visibleIds.has(identity.id))];
      agents = liveAgents;
      error = '';
      if (expanded) instances[expanded] = await identityInstances(expanded);
    }
    catch { error = 'Roster is unavailable'; }
  }
  async function toggle(identity: Identity) {
    if (expanded === identity.id) { expanded = ''; return; }
    expanded = identity.id;
    if (!instances[identity.id]) {
      try { instances[identity.id] = await identityInstances(identity.id); }
      catch { error = 'Could not load instances'; }
    }
  }
  onMount(() => {
    load();
    const stopSnapshot = onSnapshot(['agents', 'orchestrators'], load);
    const stopRefresh = refreshWhenVisible(load);
    return () => { stopSnapshot(); stopRefresh(); };
  });
</script>
<Section title="Roster" count={identities.length}>
  {#if error}<p role="status">{error}</p>{/if}
  {#if listFiltered}<p class="roles-note">All roles</p>{/if}
  <ul>{#each identities as identity (identity.id)}
    <li>
      <div class="line">
        {#if identity.role === 'orchestrator' || identity.role === 'planner'}
          <button class="summary" aria-expanded={expanded === identity.id} onclick={() => toggle(identity)}>
            <strong>{identity.name}</strong><span>{counts[identity.role] ?? 0}</span><Badge tone={stateTone(identity.worst_state)}>{stateLabel(identity.worst_state)}</Badge>
          </button>
        {:else}
          <div class="summary"><strong>{identity.name}</strong><span>{counts[identity.role] ?? 0}</span><Badge tone={stateTone(identity.worst_state)}>{stateLabel(identity.worst_state)}</Badge></div>
        {/if}
        {#if identity.error !== 'unknown identity'}<a class="profile-link" aria-label={linkLabels[identity.id]} href={`/agents/profile/${encodeURIComponent(identity.id)}`}>Edit profile</a>{/if}
      </div>
      {#if identity.error}<p class="error">{identity.error}</p>{/if}
      {#if expanded === identity.id}<ul class="instances">{#each instances[identity.id] ?? [] as instance (instance.agent_id)}<li><a href={`/thread/${encodeURIComponent(instance.agent_id)}`}>{instance.label}</a><Badge tone={stateTone(instance.state)}>{stateLabel(instance.state)}</Badge></li>{/each}</ul>{/if}
    </li>
  {/each}</ul>
</Section>
<style>
  ul{list-style:none;padding:0;margin:0}.line{display:flex;align-items:center;gap:var(--space-2);width:100%;min-height:44px;padding:var(--space-2) 0;border:0;border-top:var(--line) solid var(--border-subtle);background:transparent;color:var(--text-body);text-align:left;flex-wrap:wrap}.summary{display:flex;flex:1;align-items:center;gap:var(--space-2);min-width:0;min-height:44px;padding:0;border:0;background:transparent;color:inherit;font:inherit;text-align:left;flex-wrap:wrap}.summary[aria-expanded]{cursor:pointer}.summary strong{flex:1;min-width:7.5rem;color:var(--text-strong);overflow-wrap:anywhere}.roles-note{display:none;margin:0 0 var(--space-2);color:var(--text-muted);font-size:var(--font-size-sm)}.summary span{overflow-wrap:anywhere}.profile-link{display:flex;align-items:center;min-height:44px;padding:0 var(--space-2);color:var(--accent);white-space:nowrap}.instances{padding-left:var(--space-3)}.instances li{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:var(--space-2);min-height:44px;border-top:var(--line) solid var(--border-subtle);overflow-wrap:anywhere}.instances a{display:flex;align-items:center;min-width:0;min-height:44px;color:var(--text-strong);overflow-wrap:anywhere}.error{color:var(--status-blocked-fg);overflow-wrap:anywhere}
  @media(max-width:480px){.summary,.profile-link{flex-basis:100%}.profile-link{justify-content:flex-end}}
  @media(max-width:1099px){.roles-note{display:block}}
</style>
