<script lang="ts">
  import { groupedSections } from './settingsNav';
  const groups = groupedSections();
  const paths: Record<string, string> = { harnesses: 'plug', runner: 'terminal', 'role-types': 'users', 'model-types': 'layers', display: 'sun', review: 'clock', status: 'pulse' };
</script>
<nav class="settings-nav" aria-label="Settings sections">
  {#each Object.entries(groups) as [group, sections] (group)}
    <section class="nav-group" aria-label={group}>
      <h2>{group}</h2>
      {#each sections as section (section.id)}
        <a href={'/settings/' + section.id} data-settings-row={section.id}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d={iconPath(paths[section.id])} /></svg>
          <span><strong>{section.label}</strong><small>{section.summary}</small></span>
          <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
        </a>
      {/each}
    </section>
  {/each}
</nav>
<script module lang="ts">
  function iconPath(name: string) {
    const paths: Record<string, string> = {
      plug: 'M9 7V3m6 4V3M8 7h8v5a4 4 0 0 1-4 4v5m-6-9H4m16 0h-2',
      terminal: 'm4 17 6-5-6-5m8 10h8', users: 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2m6-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8m6-7a4 4 0 0 1 0 8m2 3h2a3 3 0 0 1 3 3v2',
      layers: 'm12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5m-18 5 9 5 9-5', sun: 'M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4m0-12.8L17 7M7 17l-1.4 1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
      clock: 'M12 8v4l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0', pulse: 'M3 12h4l3-8 4 16 3-8h4'
    };
    return paths[name] ?? paths.pulse;
  }
</script>
<style>
  .settings-nav{display:grid;gap:var(--space-5);min-width:0}.nav-group{display:grid;gap:var(--space-2);min-width:0}.nav-group h2{margin:0;color:var(--text-muted);font-size:var(--font-size-xs);font-weight:700;letter-spacing:.08em;text-transform:uppercase}
  a{display:flex;align-items:center;gap:var(--space-3);min-width:0;min-height:var(--nav-item-h);padding:var(--space-2) var(--space-3);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);color:var(--text-body);text-decoration:none}a:hover,a:focus-visible{border-color:var(--accent);background:var(--surface-selected)}
  a>svg{width:var(--icon-size);height:var(--icon-size);flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;color:var(--text-muted)}a>span{display:grid;gap:var(--space-1);min-width:0;flex:1}strong{font-size:var(--font-size-sm)}small{color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}.chevron{width:var(--icon-size)}
</style>
