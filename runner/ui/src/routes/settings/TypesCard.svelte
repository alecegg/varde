<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { Button, Section } from '../../lib/ui';
  import { choicesFor, emptyTypesMessage, fallbackMoveAnnouncement, harnessOptions, moveFallback, typeChanges, typesFromItems, unavailableChoiceHarnesses, validateFallbacks, type ConfigChoices, type TypeConfig } from './types';
  import { displayHarnessName } from './displayNames';

  let choices: ConfigChoices = $state({});
  let types: TypeConfig[] = $state([]);
  let error = $state('');
  let status = $state('');
  let previewed = $state(false);
  let busy = $state(false);
  let loading = $state(true);
  let fallbackAnnouncement = $state('');
  let unavailableHarnesses = $derived(unavailableChoiceHarnesses(types, choices));

  function harnessChoices(selected: string) {
    return [...new Set([selected, ...harnessOptions(choices)].filter(Boolean))];
  }

  async function requestConfig(changes?: Record<string, unknown>, preview = false) {
    const response = await fetch('/api/runner/config' + (changes ? '' : ''), changes ? {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ changes, preview }),
    } : { cache: 'no-store' });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error ?? Object.values(body.errors ?? {})[0] ?? 'Could not update type settings.');
    return body;
  }
  async function load() {
    try {
      const data = await requestConfig();
      choices = data.choices ?? {};
      types = typesFromItems(data.items ?? []);
      error = '';
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Could not load type settings.'; }
    finally { loading = false; }
  }
  async function preview() {
    if (types.some((item) => validateFallbacks(item.fallback).some(Boolean))) {
      error = 'Complete every fallback harness, model, and effort before previewing.';
      return;
    }
    busy = true; error = ''; status = '';
    try { await requestConfig(typeChanges(types), true); previewed = true; status = 'Preview ready. Review the values above, then save.'; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not preview these changes.'; previewed = false; }
    finally { busy = false; }
  }
  async function save() {
    if (!previewed) return;
    busy = true; error = ''; status = '';
    try { const result = await requestConfig(typeChanges(types)); status = result.restart_required ? 'Saved. Restart the runner to apply these changes.' : 'Saved.'; previewed = false; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Could not save type settings.'; }
    finally { busy = false; }
  }
  function addFallback(item: TypeConfig) {
    const harness = harnessOptions(choices)[0];
    if (!harness) return;
    const options = choicesFor(choices, harness);
    item.fallback = [...item.fallback, { harness, model: options.models[0] ?? '', reasoning_effort: options.reasoning_efforts[0] ?? '' }];
    previewed = false;
  }
  function setFallbackHarness(item: TypeConfig, index: number, harness: string) {
    const options = choicesFor(choices, harness);
    item.fallback = item.fallback.map((fallback, current) => current === index
      ? { harness, model: options.models[0] ?? '', reasoning_effort: options.reasoning_efforts[0] ?? '' }
      : fallback);
    previewed = false;
  }
  async function moveFallbackItem(item: TypeConfig, index: number, offset: -1 | 1, direction: 'up' | 'down') {
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= item.fallback.length) return;
    item.fallback = moveFallback(item.fallback, index, offset);
    previewed = false;
    fallbackAnnouncement = fallbackMoveAnnouncement(index + 1, nextIndex + 1);
    await tick();
    const preferred = direction === 'up' && nextIndex === 0 ? 'down' : direction === 'down' && nextIndex === item.fallback.length - 1 ? 'up' : direction;
    document.querySelector<HTMLElement>(`[data-fallback-index="${nextIndex}"] button[aria-label="Move fallback ${nextIndex + 1} ${preferred}"]`)?.focus();
  }
  onMount(load);
</script>

<Section title="Model types">
  <div aria-busy={loading}>
  <p class="visually-hidden" role="status">{fallbackAnnouncement}</p>
  {#if loading}
    <div class="loading-types" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span></div>
  {:else if types.length}<p class="note first">Choose a tool, model, reasoning level, and backup options for each type.</p>
  {:else}<p class="note first">{emptyTypesMessage}</p><p><a href="/roles">Edit models and fallbacks on the Roles page</a></p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if unavailableHarnesses.length}<p class="help">No models or reasoning levels are available for {unavailableHarnesses.map(displayHarnessName).join(', ')}. Go to <a href="/settings/harnesses">Tool settings</a> to enable or sign in to them, then reload this page.</p>{/if}
  {#each loading ? [] : types as item (item.name)}
    <fieldset>
      <legend>{item.name.charAt(0).toUpperCase() + item.name.slice(1)}</legend>
      <label>Tool<small>Choose the tool used for this model type.</small><select bind:value={item.harness} onchange={() => previewed = false}>
        {#if !item.harness}<option value="" disabled>Choose a tool</option>{/if}
        {#each harnessChoices(item.harness) as option}<option value={option}>{displayHarnessName(option)}</option>{/each}
      </select></label>
      {#if choicesFor(choices, item.harness).models.length}
        <label>Model<small>Choose the model used for this type.</small><select bind:value={item.model} onchange={() => previewed = false}>
          {#each choicesFor(choices, item.harness).models as option}<option value={option}>{option}</option>{/each}
        </select></label>
      {/if}
      {#if choicesFor(choices, item.harness).reasoning_efforts.length}
        <label>Reasoning level<small>Choose the reasoning level for this type.</small><select bind:value={item.reasoning_effort} onchange={() => previewed = false}>
          {#each choicesFor(choices, item.harness).reasoning_efforts as option}<option value={option}>{option}</option>{/each}
        </select></label>
      {/if}
      <div class="fallback-list">
        <div class="fallback-heading"><strong>Fallback choices</strong><small>Try these tool and model combinations in order if the main model is unavailable.</small></div>
        {#each item.fallback as fallback, index (fallback)}
          {@const fallbackChoices = choicesFor(choices, fallback.harness)}
          {@const fallbackErrors = validateFallbacks(item.fallback)}
          <div class="fallback-item" role="group" aria-label={`Fallback ${index + 1}`} data-fallback-index={index}>
            <strong class="fallback-legend">Fallback {index + 1}</strong>
            <label>Tool<small>Choose the tool for this fallback.</small><select value={fallback.harness} onchange={(event) => setFallbackHarness(item, index, event.currentTarget.value)}>
              {#if !fallback.harness}<option value="" disabled>Choose a tool</option>{/if}
              {#each harnessChoices(fallback.harness) as option}<option value={option}>{displayHarnessName(option)}</option>{/each}
            </select></label>
            {#if fallbackChoices.models.length}
              <label>Model<small>Choose a model available in this harness.</small><select bind:value={fallback.model} onchange={() => previewed = false}>
                {#each fallbackChoices.models as option}<option value={option}>{option}</option>{/each}
              </select></label>
            {/if}
            {#if fallbackChoices.reasoning_efforts.length}
              <label>Reasoning level<small>Choose the reasoning level for this fallback.</small><select bind:value={fallback.reasoning_effort} onchange={() => previewed = false}>
                {#each fallbackChoices.reasoning_efforts as option}<option value={option}>{option}</option>{/each}
              </select></label>
            {/if}
            {#if fallbackErrors[index]}<p class="error" role="alert">{fallbackErrors[index]}</p>{/if}
            <div class="fallback-actions">
              {#if item.fallback.length > 1}
                <Button variant="secondary" aria-label={`Move fallback ${index + 1} up`} disabled={index === 0} onclick={() => moveFallbackItem(item, index, -1, 'up')}>Move up</Button>
                <Button variant="secondary" aria-label={`Move fallback ${index + 1} down`} disabled={index === item.fallback.length - 1} onclick={() => moveFallbackItem(item, index, 1, 'down')}>Move down</Button>
              {/if}
              <Button variant="secondary" aria-label={`Remove fallback ${index + 1}`} onclick={() => { item.fallback = item.fallback.filter((_, current) => current !== index); previewed = false; }}>Remove fallback</Button>
            </div>
          </div>
        {:else}<p class="help">No fallbacks configured.</p>{/each}
        {#if harnessOptions(choices).length}<Button variant="secondary" onclick={() => addFallback(item)}>Add fallback</Button>
        {:else}<p class="help">Fallbacks are unavailable because no harness choices were provided.</p>{/if}
      </div>
    </fieldset>
  {/each}
  {#if types.length}<div class="actions"><Button variant="secondary" disabled={busy} onclick={preview}>{busy ? 'Working…' : 'Preview changes'}</Button><Button disabled={busy || !previewed} title={!previewed ? 'Preview your changes before saving.' : undefined} onclick={save}>Save</Button></div>{#if !previewed}<p class="help preview-help">Preview your changes before saving.</p>{/if}{/if}
  {#if status}<p class="note" role="status">{status}</p>{/if}
  </div>
</Section>

<style>
    .note,.help{margin:var(--space-2) 0;color:var(--text-muted);font-size:var(--font-size-xs)}.note.first{margin-top:0}.preview-help{margin-top:0}.error{color:var(--status-blocked-fg)}p a{display:inline-flex;align-items:center;min-height:var(--control-h);max-width:100%;color:var(--text-link)}fieldset{min-width:0;margin:var(--space-3) 0;padding:var(--space-3);border:var(--line) solid var(--border);border-radius:var(--radius-control)}legend,.fallback-legend{font-weight:600}label{display:grid;gap:var(--space-1);margin:var(--space-2) 0;font-size:var(--font-size-sm)}label small,.fallback-heading small{color:var(--text-muted);font-size:var(--font-size-xs)}select{box-sizing:border-box;width:100%;height:44px;min-width:0;min-height:44px;padding:var(--space-2);border:var(--line) solid var(--border);border-radius:var(--radius-control);background:var(--surface-0);color:var(--text-body);font:inherit;font-size:16px}.actions,.fallback-actions{display:flex;flex-wrap:wrap;gap:var(--space-2)}.fallback-list{display:grid;gap:var(--space-2);margin-top:var(--space-4)}.fallback-heading{display:grid;gap:var(--space-1)}.fallback-item{display:grid;gap:var(--space-2);margin:0;padding:var(--space-3);border:var(--line) solid var(--border);border-radius:var(--radius-control);background:var(--surface-1)}.loading-types{display:grid;gap:var(--space-3);min-height:22rem}.loading-types span{height:6rem;border-radius:var(--radius-control);background:var(--surface-1)}.actions{position:sticky;bottom:0;z-index:2;padding:var(--space-2);background:var(--surface-1);border-top:var(--line) solid var(--border)}
</style>
