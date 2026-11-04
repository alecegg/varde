<script lang="ts">
  let { name, agentId, status }: { name: string; agentId: string; status?: string } = $props();
  const agents: Record<string, { initials: string; hue: string }> = {
    manager: { initials: 'MG', hue: 'violet' },
    builder: { initials: 'BU', hue: 'blue' },
    reviewer: { initials: 'RE', hue: 'green' },
    planner: { initials: 'PL', hue: 'orange' },
    explorer: { initials: 'EX', hue: 'pink' },
  };
  const avatar = $derived(agents[agentId] ?? { initials: name.trim().slice(0, 2).toUpperCase() || '?', hue: 'violet' });
  const state = $derived(['running', 'queued', 'needs_you'].includes(status ?? '') ? (status === 'needs_you' ? 'needs-you' : status) : '');
</script>

<header class="thread-header">
  <span class={`avatar ${avatar.hue} ${state}`} aria-hidden="true">{avatar.initials}</span>
  <div class="identity">
    <h1 title={name}>{name}</h1>
  </div>
</header>

<style>
  .thread-header{display:flex;align-items:center;gap:12px;min-width:0;min-height:60px;margin-bottom:8px;background:transparent;color:var(--cf-text)}
  .avatar{position:relative;display:grid;place-items:center;flex:none;width:44px;height:44px;border-radius:50%;color:#fff;font-size:14px;font-weight:700}
  .violet{background:var(--cf-avatar-violet)}.blue{background:var(--cf-avatar-blue)}.green{background:var(--cf-avatar-green)}.orange{background:var(--cf-avatar-orange)}.pink{background:var(--cf-avatar-pink)}
  .avatar.running::after,.avatar.queued::after,.avatar.needs-you::after{content:"";position:absolute;right:0;bottom:0;width:14px;height:14px;border:2px solid var(--cf-panel);border-radius:50%}
  .avatar.running::after{background:#16834b}.avatar.queued::after{background:#b36c00}.avatar.needs-you::after{background:var(--cf-accent)}
  .identity{display:grid;gap:2px;min-width:0}
  h1{overflow:hidden;margin:0;color:var(--cf-text);font-size:19px;font-weight:700;line-height:1.25;text-overflow:ellipsis;white-space:nowrap}
</style>
