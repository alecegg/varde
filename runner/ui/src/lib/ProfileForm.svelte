<script lang="ts">
  import { saveIdentity, IdentitySaveError, type Identity, type ProfileFields } from './identitiesApi';
  import { validateProfile } from './profileForm';
  import { Button, Card, Input, Textarea } from './ui';

  let { identity }: { identity: Identity } = $props();
  let fields = $state<ProfileFields>({ name: '', label: '', description: '' });
  let initialized = false;
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let saved = $state(false);
  let submitError = $state('');

  $effect(() => {
    if (initialized) return;
    fields = { name: identity.name, label: identity.label, description: identity.description };
    initialized = true;
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    errors = validateProfile(fields);
    saved = false;
    submitError = '';
    if (Object.keys(errors).length) return;
    saving = true;
    try {
      await saveIdentity(identity.id, fields);
      saved = true;
    } catch (error) {
      if (error instanceof IdentitySaveError) errors = error.errors;
      else submitError = 'Could not save profile. Check your connection and retry.';
    } finally { saving = false; }
  }
</script>

<Card>
  {#if identity.error}<p class="file-error" role="alert">This profile file is invalid: {identity.error}. Defaults are shown; saving will replace the invalid file.</p>{/if}
  {#if submitError}<p class="submit-error" role="alert">{submitError}</p>{/if}
  <form onsubmit={submit}>
    <Input label="Name" bind:value={fields.name} maxlength={40} error={errors.name} autocomplete="off" />
    <Input label="Label" bind:value={fields.label} maxlength={24} error={errors.label} autocomplete="off" />
    <Textarea label="Description" bind:value={fields.description} maxlength={280} error={errors.description} />
    <div class="role"><span>Role</span><strong>{identity.role}</strong></div>
    <div class="actions"><Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</Button>{#if saved}<span role="status">Saved</span>{/if}</div>
  </form>
</Card>

<style>
  form{display:grid;gap:var(--space-4);width:100%;min-width:0}
  .file-error,.submit-error{margin:0;padding:var(--space-3);border-radius:var(--radius-control);background:var(--status-blocked-bg);color:var(--status-blocked-fg);overflow-wrap:anywhere}
  .role{display:grid;gap:var(--space-1);min-height:var(--control-h);align-content:center;color:var(--text-secondary)}
  .role strong{color:var(--text-body);font-weight:500}
  .actions{display:flex;align-items:center;gap:var(--space-3);min-height:var(--control-h)}
  @media(max-width:480px){form{gap:var(--space-3)}}
</style>
