<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { Button, Section } from '../../lib/ui';
  import { guardOk, summarizeRoleChanges, toToml, type ModelType, type Role } from '../roles/roles';
  import { displayChoiceName } from './displayNames';

  let roles: Record<string, Role> = $state({});
  let types: Record<string, ModelType> = $state({});
  let toml = $state('');
  let originalToml = $state('');
  let guardInFile = $state(false);
  let error = $state('');
  let status = $state('');
  let preview: { preview_token: string; diff: string } | null = $state(null);
  let busy = $state(false);
  let loading = $state(true);
  let previewElement: HTMLElement | undefined = $state();
  let guardEligible = $derived(!roles.guard || guardOk(types, roles.guard));
  let summary = $derived(summarizeRoleChanges(originalToml, toml));

  async function request(path: string, body: object) {
    const response = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error ?? 'Could not update role settings.');
    return data;
  }
  async function load() {
    try {
      const response = await fetch('/api/roles', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? 'Could not load roles.');
      toml = data.toml; originalToml = data.toml; roles = data.roles ?? {}; types = data.types ?? {}; guardInFile = data.guard_in_file === true; error = '';
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load roles.'; }
    finally { loading = false; }
  }
  async function makePreview() {
    busy = true; error = ''; status = ''; preview = null;
    try {
      toml = toToml(types, roles, toml);
      preview = await request('/api/roles/preview', { toml });
      await tick();
      previewElement?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not preview role changes.'; }
    finally { busy = false; }
  }
  async function save() {
    if (!preview) return;
    busy = true; error = ''; status = '';
    try { await request('/api/roles/save', { toml, preview_token: preview.preview_token }); preview = null; originalToml = toml; guardInFile = true; status = 'Role settings saved. Restart the runner to apply them.'; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not save role changes.'; }
    finally { busy = false; }
  }
  onMount(load);
</script>

<Section title="Role types">
  <div aria-busy={loading}>
  <p class="note first">Assign each role to a shared type. Detailed model choices remain on the <a href="/roles">Roles page</a>.</p>
  {#if loading}<div class="loading-roles" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span><span></span></div>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#each loading ? [] : Object.entries(roles) as [name, role] (name)}
    <label class="role">{displayChoiceName(name)}<select value={role.type ?? ''} onchange={(event) => { role.type = event.currentTarget.value; preview = null; status = ''; }}>
      {#each Object.keys(types) as type}<option value={type}>{displayChoiceName(type)}</option>{/each}
    </select></label>
    {#if name === 'guard' && !guardEligible}<p class="error" role="alert">Guard requires a verified read-only harness. Choose an eligible type before previewing.</p>{/if}
  {/each}
  {#if !loading && !guardInFile}<p class="note">Saving adds Guard to the runner settings, but does not turn it on.</p>{/if}
  {#if !loading}<div class="actions"><Button variant="secondary" disabled={busy || !guardEligible} title={!guardEligible ? 'Choose a verified read-only harness for Guard before previewing.' : undefined} onclick={makePreview}>{busy ? 'Working…' : 'Preview role changes'}</Button>
    {#if preview}<Button disabled={busy} onclick={save}>Save role changes</Button>{/if}</div>
  {/if}
  {#if preview}<div class="preview" bind:this={previewElement}>
    {#if summary.lines.length}<ul aria-label="Role change summary">{#each summary.lines as line (line)}<li>{line}</li>{/each}</ul>{/if}
    {#if summary.unrelated.length}<p class="warning" role="alert">Other changed settings: {summary.unrelated.join(', ')}</p>{/if}
    {#if !summary.lines.length && !summary.unrelated.length}<p>No role assignments will change.</p>{/if}
  </div>{/if}
  {#if status}<p class="note" role="status">{status}</p>{/if}
  </div>
</Section>

<style>
  .note{margin:var(--space-2) 0;color:var(--text-muted);font-size:var(--font-size-xs);line-height:1.45}.note.first{margin-top:0}.note a{color:var(--text-link)}.error,.warning{color:var(--status-blocked-fg)}.role{display:grid;gap:var(--space-1);margin:var(--space-2) 0}.role select{box-sizing:border-box;width:100%;height:44px;min-width:0;min-height:44px;padding:var(--space-2);border:var(--line) solid var(--border);border-radius:var(--radius-control);background:var(--surface-0);color:var(--text-body);font:inherit;font-size:16px}.actions{position:sticky;bottom:0;z-index:2;display:flex;flex-wrap:wrap;gap:var(--space-2);padding:var(--space-2);background:var(--surface-1);border-top:var(--line) solid var(--border)}.loading-roles{display:grid;gap:var(--space-3);min-height:26rem}.loading-roles span{height:3rem;border-radius:var(--radius-control);background:var(--surface-1)}.preview ul{margin:0 0 var(--space-2);padding-left:var(--space-4);color:var(--text-body);font-size:var(--font-size-sm);line-height:1.45}.preview li,.warning{overflow-wrap:anywhere}.warning{margin:var(--space-2) 0}
</style>
