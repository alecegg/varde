<script lang="ts">
  import { tick } from 'svelte';
  import { Button, Section } from '../../lib/ui';
  import { diffRows } from './sdkFlip';
  import { affectedText, rolesAffected } from './sdkRoles';

  type FlipPreview = { preview_id: string; diff: { key: string; before: unknown; after: unknown }[]; restart_required: boolean };
  let preview: FlipPreview | null = $state(null);
  let error = $state('');
  let status = $state('');
  let busy = $state(false);
  let roleSummary = $state('No roles need changes; this enables Claude Code for them.');

  async function closeReview() {
    preview = null;
    error = '';
    await tick();
    document.querySelector<HTMLButtonElement>('[data-sdk-review-trigger]')?.focus();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && preview) {
      event.preventDefault();
      void closeReview();
    }
  }

  async function request(path: string, body?: object) {
    const response = await fetch(path, body ? {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    } : { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error ?? 'Could not update Claude Code settings.');
    return data;
  }

  async function openReview() {
    busy = true; error = ''; status = ''; preview = null;
    try {
      const [nextPreview, rolesResponse] = await Promise.all([
        request('/api/runner/config/sdk-flip/preview'), fetch('/api/roles', { cache: 'no-store' }),
      ]);
      const roleData = await rolesResponse.json();
      if (!rolesResponse.ok) throw new Error(roleData.error ?? 'Could not load roles for the Claude Code review.');
      preview = nextPreview;
      roleSummary = affectedText(rolesAffected(nextPreview.diff, roleData.roles ?? {}));
    }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not preview Claude Code changes.'; }
    finally { busy = false; }
  }

  async function confirmApply() {
    if (!preview || busy) return;
    busy = true; error = ''; status = '';
    try {
      const result = await request('/api/runner/config/sdk-flip/apply', { confirm: true, preview_id: preview.preview_id });
      preview = null;
      status = result.restart_required ? 'Claude Code settings saved. Restart the runner to apply them.' : 'Claude Code settings already match.';
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not apply Claude Code settings.'; }
    finally { busy = false; }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<Section title="Move Claude roles to Claude Code">
  <p class="note first">Preview the configuration changes before enabling Claude Code for these roles.</p>
  <Button variant="secondary" disabled={busy} data-sdk-review-trigger onclick={openReview}>{busy ? 'Preparing preview…' : 'Preview Claude Code changes'}</Button>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if status}<p class="note" role="status">{status}</p>{/if}
</Section>

{#if preview}
  <div class="backdrop" role="presentation">
    <dialog open class="sheet" aria-labelledby="sdk-review-title" aria-modal="true">
      <h2 id="sdk-review-title">Review Claude Code changes</h2>
      <p class="note">Confirm only after reviewing each changed value.</p>
      <p class="note">{roleSummary}</p>
      <ul aria-label="Claude Code configuration changes">
        {#each diffRows(preview.diff) as row}<li>{row}</li>{:else}<li>No changes.</li>{/each}
      </ul>
      {#if preview.restart_required}<p class="note">Restart the runner after applying these changes.</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <div class="actions">
        <Button disabled={busy} onclick={confirmApply}>{busy ? 'Applying…' : 'Confirm and apply'}</Button>
        <Button variant="secondary" disabled={busy} onclick={closeReview}>Cancel</Button>
      </div>
    </dialog>
  </div>
{/if}

<style>
  .note{margin:var(--space-2) 0;color:var(--text-muted);font-size:var(--font-size-xs)}.note.first{margin-top:0}.error{color:var(--status-blocked-fg)}.backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:var(--space-3);background:rgb(0 0 0 / .48)}.sheet{box-sizing:border-box;width:min(36rem,100%);max-height:min(85vh,48rem);overflow:auto;margin:0;padding:var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);color:var(--text-body);box-shadow:var(--elevation-dialog)}h2{margin:0 0 var(--space-2);font-size:var(--font-size-lg);color:var(--text-strong)}ul{max-height:48vh;overflow:auto;padding:var(--space-3) var(--space-3) var(--space-3) var(--space-6);border-radius:var(--radius-control);background:var(--surface-code);color:var(--code);font-size:var(--font-size-xs)}.actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}
</style>
