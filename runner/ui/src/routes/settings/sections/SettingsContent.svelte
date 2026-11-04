<script lang="ts">
  import { onMount } from 'svelte';
  let { section = '' }: { section?: string } = $props();
  import { Section } from '../../../lib/ui';
  import { formatDateTime } from '../../../lib/ui/date';
  import { Button } from '../../../lib/ui';
  import { api } from '../../../lib/queue';
  import type { Row } from '../../../lib/plans';
  import InfrastructureCard from '../../../lib/InfrastructureCard.svelte';
  import OtherAgentsCard from '../../../lib/OtherAgentsCard.svelte';
  import TypesCard from '../TypesCard.svelte';
  import RolesCard from '../RolesCard.svelte';
  import SdkFlipCard from '../SdkFlipCard.svelte';
  import { checklistSteps, stepLink } from '../firstRun';
  import { savedMessage } from '../savedMessage';
  import { userSettings } from '../userSettings';
  import { displayHarnessName } from '../displayNames';
  import MailSoakCard from '../../../lib/MailSoakCard.svelte';
  import { applyTheme, savedThemeMode, type ThemeMode } from '../../../lib/theme';
  import type { AppIcon } from '../../../lib/appIcon';
  import {
    ConfigApiError, groupItems, initialDraft, loadRunnerConfig, loadRunnerStatus, restartNotice,
    restartRunner, saveRunnerConfig, validateValue,
    type ConfigItem, type ConfigValue, type RunnerStatus
  } from '../../../lib/runnerConfigApi';

  type SweepSnapshot = { last_run_at: string | null; counts: Record<string, number>; failures: Record<string, unknown>[]; next_run_at: string; state: string; digest: { date?: string; text?: string; candidates?: { title: string }[] } | null; model_tokens: number | null; summary_error: string | null };
  type Draft = string | boolean;
  type IconOption = { id: AppIcon; name: string };
  const themes: { mode: ThemeMode; label: string }[] = [{ mode: 'light', label: 'Light' }, { mode: 'dark', label: 'Dark' }, { mode: 'system', label: 'System' }];
  const iconOptions: IconOption[] = [{ id: 'slate-bronze', name: 'Slate bronze' }, { id: 'dark', name: 'Dark' }];
  let selectedIcon = $state<AppIcon>('slate-bronze');
  let iconError = $state('');
  let themeMode = $state<ThemeMode>('system');
  let sweep = $state<SweepSnapshot | null>(null), sweepError = $state(''), sweepRunning = $state(false);
  let infrastructure: Row[] = $state([]), agents: Row[] = $state([]);
  let configItems = $state<ConfigItem[]>([]);
  let configLoaded = $state(false);
  let runnerStatus = $state<RunnerStatus | null>(null);
  let runnerStatusLoaded = $state(false);
  let dashboardLoaded = $state(false);
  let configError = $state(''), statusError = $state(''), saveStatus = $state('');
  let dataRootCopyMessage = $state('');
  let drafts = $state<Record<string, Draft>>({});
  let fieldErrors = $state<Record<string, string>>({});
  let savingKey = $state(''), restartRequired = $state(false), restarting = $state(false);
  let savedMessages = $state<Record<string, string>>({});
  const savedTimers = new Map<string, ReturnType<typeof setTimeout>>();
  let groups = $derived(groupItems(configItems));
  let steps = $derived(checklistSteps(runnerStatus ?? {}));
  let incompleteSteps = $derived(steps.filter((step) => !step.done));

  function applyStatus(data: Row) { infrastructure = data.infrastructure ?? []; agents = data.agents ?? []; dashboardLoaded = true; }
  async function loadDashboardStatus() { try { applyStatus(await api<Row>('/api/orchestrators')); } catch { /* Keep the last status. */ } finally { dashboardLoaded = true; } }
  async function loadSweep() {
    try {
      const response = await fetch('/api/learn/sweep');
      if (!response.ok) throw new Error('Could not load session review status');
      sweep = await response.json();
      sweepError = '';
    } catch (error) { sweepError = error instanceof Error ? error.message : 'Could not load session review status'; }
  }
  async function runSweep() {
    sweepRunning = true;
    sweepError = '';
    try {
      const response = await fetch('/api/learn/sweep/run', { method: 'POST' });
      if (!response.ok) throw new Error('Could not run session review');
      sweep = await response.json();
    } catch (error) { sweepError = error instanceof Error ? error.message : 'Could not run session review'; }
    finally { sweepRunning = false; }
  }
  function displayTime(value: string | null) { return formatDateTime(value) ?? 'Not run yet'; }
  async function loadRunner() {
    const [configResult, statusResult] = await Promise.allSettled([loadRunnerConfig(), loadRunnerStatus()]);
    if (configResult.status === 'fulfilled') {
      configItems = userSettings(configResult.value);
      drafts = Object.fromEntries(configItems.map((item) => [item.key, initialDraft(item)]));
      configError = '';
    } else configError = configResult.reason instanceof Error ? configResult.reason.message : 'Could not load runner config';
    configLoaded = true;
    if (statusResult.status === 'fulfilled') {
      runnerStatus = statusResult.value;
      statusError = '';
    } else statusError = statusResult.reason instanceof Error ? statusResult.reason.message : 'Could not load runner status';
    runnerStatusLoaded = true;
  }
  function chooseTheme(mode: ThemeMode) {
    themeMode = mode;
    applyTheme(mode);
  }
  function onChoiceKeydown<T extends string>(event: KeyboardEvent, values: T[], choose: (value: T) => void) {
    const directions: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    const direction = directions[event.key];
    if (!direction) return;
    const group = (event.currentTarget as HTMLButtonElement).closest('[role="radiogroup"]');
    if (!group) return;
    const radios = Array.from(group.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
    const selectedIndex = radios.findIndex((radio) => radio.getAttribute('aria-checked') === 'true');
    const currentIndex = selectedIndex >= 0 ? selectedIndex : radios.indexOf(event.currentTarget as HTMLButtonElement);
    const nextIndex = (currentIndex + direction + radios.length) % radios.length;
    event.preventDefault();
    choose(values[nextIndex]);
    radios[nextIndex]?.focus();
  }
  async function loadAppIcon() {
    try {
      const response = await fetch('/api/settings', { cache: 'no-store' });
      if (!response.ok) throw new Error('Could not load app icon settings.');
      const settings = await response.json();
      if (settings.app_icon === 'dark' || settings.app_icon === 'slate-bronze') selectedIcon = settings.app_icon;
      iconError = '';
    } catch (error) { iconError = error instanceof Error ? error.message : 'Could not load app icon settings.'; }
  }
  async function chooseIcon(icon: AppIcon) {
    const previousIcon = selectedIcon;
    selectedIcon = icon;
    iconError = '';
    try {
      const response = await fetch('/api/settings', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ app_icon: icon }),
      });
      if (!response.ok) throw new Error('Could not save the app icon.');
      selectedIcon = (await response.json()).app_icon;
      window.dispatchEvent(new CustomEvent('runner:app-icon', { detail: selectedIcon }));
    } catch (error) {
      selectedIcon = previousIcon;
      iconError = error instanceof Error ? error.message : 'Could not save the app icon.';
    }
  }
  function setDraft(key: string, value: Draft) {
    drafts = { ...drafts, [key]: value };
    fieldErrors = { ...fieldErrors, [key]: '' };
    clearSavedMessage(key);
    saveStatus = '';
  }
  function clearSavedMessage(key: string) {
    const timer = savedTimers.get(key);
    if (timer) clearTimeout(timer);
    savedTimers.delete(key);
    const next = { ...savedMessages };
    delete next[key];
    savedMessages = next;
  }
  function showSavedMessage(key: string, message: string) {
    clearSavedMessage(key);
    savedMessages = { ...savedMessages, [key]: message };
    savedTimers.set(key, setTimeout(() => clearSavedMessage(key), 4000));
  }
  function isRoleHarnessRefusal(item: ConfigItem, value: ConfigValue, error: ConfigApiError): boolean {
    return item.group === 'harnesses' && value === false
      && Object.values(error.errors).some((message) => message.includes('resulting config is invalid'));
  }
  async function saveItem(item: ConfigItem) {
    const draft = drafts[item.key];
    const validation = validateValue(item, draft ?? '');
    if (validation) {
      fieldErrors = { ...fieldErrors, [item.key]: validation };
      saveStatus = '';
      return;
    }
    const value: ConfigValue = item.type === 'integer' ? Number(draft) : draft as boolean;
    savingKey = item.key;
    fieldErrors = { ...fieldErrors, [item.key]: '' };
    clearSavedMessage(item.key);
    saveStatus = '';
    try {
      const result = await saveRunnerConfig({ [item.key]: value });
      configItems = result.items;
      const savedDraft: Draft = item.type === 'boolean' && typeof draft === 'boolean' ? draft : String(value);
      drafts = { ...drafts, [item.key]: savedDraft };
      restartRequired = result.restart_required;
      if (item.group === 'runner' || item.group === 'limits' || item.group === 'bot') {
        showSavedMessage(item.key, savedMessage(result));
      } else {
        saveStatus = item.label + ' saved.';
      }
      loadRunnerStatus().then((status) => runnerStatus = status).catch(() => statusError = 'Could not refresh runner status.');
    } catch (error) {
      if (error instanceof ConfigApiError && Object.keys(error.errors).length) {
        const message = isRoleHarnessRefusal(item, value, error)
          ? 'A role uses this harness; change it in Roles first.'
          : error.errors[item.key] ?? Object.values(error.errors)[0] ?? error.message;
        fieldErrors = { ...fieldErrors, [item.key]: message };
      } else fieldErrors = { ...fieldErrors, [item.key]: error instanceof Error ? error.message : 'Could not save this setting.' };
    } finally { savingKey = ''; }
  }
  function harnessFor(item: ConfigItem) {
    const table = item.key.split('.')[0].replaceAll('_', '-').replaceAll('-', '').toLowerCase();
    return runnerStatus?.harnesses.find((harness) => harness.name.replaceAll('-', '').toLowerCase() === table);
  }
  function harnessLabel(item: ConfigItem) {
    const name = harnessFor(item)?.name ?? item.key.split('.')[0].replaceAll('_', ' ');
    return displayHarnessName(name);
  }
  function harnessSummary(item: ConfigItem) {
    const harness = harnessFor(item);
    if (!item.value || !harness) return item.value ? 'Status unavailable.' : 'Disabled. Enable to check login status.';
    if (harness.login === 'unknown') return '';
    if (harness.login === 'login_required') return 'Sign in to this harness before using it.';
    if (harness.login === 'missing') return 'Harness not found. Install it to use this option.';
    return harness.hint;
  }
  async function restart() {
    restarting = true;
    saveStatus = '';
    try {
      await restartRunner();
      saveStatus = 'Runner restart requested. Reconnect when it is back.';
      restartRequired = false;
    } catch (error) { statusError = error instanceof Error ? error.message : 'Could not restart the runner.'; }
    finally { restarting = false; }
  }
  async function copyDataRoot() {
    const dataRoot = runnerStatus?.data_root;
    if (!dataRoot) return;
    try {
      await navigator.clipboard.writeText(dataRoot);
      dataRootCopyMessage = 'Full path copied.';
    } catch {
      dataRootCopyMessage = 'Could not copy the path. Check browser clipboard permissions.';
    }
  }
  function scrollToHashTarget() {
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView({ block: 'start' });
  }
  // The browser jumps to the hash before the async cards load, so the target moves afterwards.
  function settleHashScroll() {
    if (!window.location.hash) return () => {};
    const observer = new ResizeObserver(scrollToHashTarget);
    let timer = 0;
    const stop = () => {
      observer.disconnect();
      clearTimeout(timer);
      window.removeEventListener('wheel', stop);
      window.removeEventListener('pointerdown', stop);
      window.removeEventListener('keydown', stop);
    };
    timer = window.setTimeout(stop, 2000);
    window.addEventListener('wheel', stop, { passive: true });
    window.addEventListener('pointerdown', stop);
    window.addEventListener('keydown', stop);
    observer.observe(document.body);
    return stop;
  }
  onMount(() => {
    themeMode = savedThemeMode();
    const themeChanged = (event: Event) => { themeMode = (event as CustomEvent<ThemeMode>).detail; };
    window.addEventListener('runner:theme', themeChanged);
    const snapshot = (event: Event) => { const topics = (event as CustomEvent<{ topics?: string[] }>).detail?.topics ?? []; if (topics.includes('orchestrators')) loadDashboardStatus(); };
    window.addEventListener('runner:snapshot', snapshot);
    loadDashboardStatus();
    loadSweep();
    loadRunner();
    loadAppIcon();
    const stopHashSettling = settleHashScroll();
    return () => {
      stopHashSettling();
      window.removeEventListener('runner:theme', themeChanged);
      window.removeEventListener('runner:snapshot', snapshot);
      for (const timer of savedTimers.values()) clearTimeout(timer);
      savedTimers.clear();
    };
  });
</script>

{#snippet numberSetting(item: ConfigItem)}
  <article class="setting-row">
    <label class="number-setting"><span><strong>{item.label}</strong><small>{item.hint}{#if item.bounds} ({item.bounds.min}–{item.bounds.max}){/if}</small></span><input type="number" step="1" min={item.bounds?.min ?? undefined} max={item.bounds?.max ?? undefined} value={drafts[item.key] ?? initialDraft(item)} aria-label={item.label} aria-invalid={Boolean(fieldErrors[item.key])} oninput={(event) => setDraft(item.key, event.currentTarget.value)} /></label>
    <Button variant="secondary" disabled={savingKey === item.key} onclick={() => saveItem(item)}>{savingKey === item.key ? 'Saving…' : 'Save'}</Button>
    {#if fieldErrors[item.key]}<p class="error" role="alert">{fieldErrors[item.key]}</p>{/if}
    {#if savedMessages[item.key]}<p class="saved" role="status">{savedMessages[item.key]}</p>{/if}

  </article>
{/snippet}

<svelte:head><title>Varde Runner · Settings</title></svelte:head>
<div class="stack" data-active-section={section} aria-busy={!configLoaded || !runnerStatusLoaded || !dashboardLoaded}>
  {#if !runnerStatusLoaded || incompleteSteps.length}
    <div id="first-run"><Section title="First-run checklist">
      {#if runnerStatusLoaded}<ul class="checklist">{#each incompleteSteps as step (step.id)}<li><span aria-hidden="true" class="checklist-marker"></span><a href={stepLink(step)}>{step.hint}</a></li>{/each}</ul>
      {:else}<ul class="checklist checklist-loading" aria-hidden="true">{#each [0, 1, 2, 3] as row}<li><span class="skeleton-marker"></span><span class="skeleton-line"></span></li>{/each}</ul>{/if}
    </Section></div>
  {/if}
  <div id="harnesses" class="settings-anchor" data-settings-anchor>
  <Section title="Harnesses">
    {#if configError}<p class="error" role="alert">{configError}</p>{/if}
    {#if saveStatus}<p class="saved" role="status">{saveStatus}</p>{#if restartRequired}<p class="note" role="status">{restartNotice(true)}</p>{#if runnerStatus?.service.managed}<Button disabled={restarting} onclick={restart}>{restarting ? 'Restarting…' : 'Restart runner'}</Button>{/if}{/if}{/if}
    {#if !configLoaded}<div class="loading-list" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span></div>
    {:else if groups.harnesses.length}
      {#if groups.harnesses.some((item) => item.value && harnessFor(item)?.login === 'unknown')}<p class="note first">Login status can’t be checked for some tools. Confirm you’re signed in within each tool before using it.</p>{/if}
      <div class="setting-list">{#each groups.harnesses as item (item.key)}
        <article class="harness-row">
          <label class="toggle"><input type="checkbox" checked={drafts[item.key] === true} disabled={savingKey === item.key} aria-label={'Enable ' + harnessLabel(item)} onchange={(event) => { setDraft(item.key, event.currentTarget.checked); void saveItem(item); }} /><span><strong>{harnessLabel(item)}</strong><small>{harnessSummary(item)}</small></span></label>
          {#if fieldErrors[item.key]}<p class="error" role="alert">{fieldErrors[item.key]}</p>{/if}
          {#if savedMessages[item.key]}<p class="saved" role="status">{savedMessages[item.key]}</p>{/if}
        </article>
      {/each}</div>
    {:else}<p class="note first">No configurable harnesses are registered.</p>{/if}
  </Section>
  </div>
  <div id="role-types" class="settings-anchor" data-settings-anchor><RolesCard /><SdkFlipCard /></div>
  <div id="runner" class="settings-anchor" data-settings-anchor>
  <Section title="Runner">
    {#if !runnerStatusLoaded}<div class="loading-status" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span></div>
    {:else if statusError}<p class="error" role="alert">{statusError}</p>
    {:else if runnerStatus}
      <dl class="runner-status"><div><dt>Version</dt><dd>{runnerStatus.version}</dd></div><div><dt>Data folder</dt><dd><span>Workspace data folder</span><Button variant="secondary" onclick={copyDataRoot}>Copy full path</Button>{#if dataRootCopyMessage}<small role="status">{dataRootCopyMessage}</small>{/if}</dd></div><div><dt>Service</dt><dd>{runnerStatus.service.managed ? 'Managed by ' + runnerStatus.service.kind : runnerStatus.service.installed ? 'Installed, not managing this process' : 'Not installed'}</dd></div></dl>
      {#if restartRequired}<p class="note" role="status">{restartNotice(true)}</p>{/if}
      {#if runnerStatus.service.managed}<Button disabled={restarting} onclick={restart}>{restarting ? 'Restarting…' : 'Restart runner'}</Button>
      {:else if restartRequired}<p class="note">Run varde-runner service start to restart under the service manager.</p>
      {:else}<p class="note">Changes applied immediately.</p>{/if}
    {/if}
    {#if !configLoaded}<div class="loading-list" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span></div>{/if}
    {#each configLoaded ? groups.runner : [] as item (item.key)}
      {#if item.type === 'boolean'}
        <article class="setting-row">
          <label class="toggle"><input type="checkbox" checked={drafts[item.key] === true} disabled={savingKey === item.key} aria-label={item.label} onchange={(event) => { setDraft(item.key, event.currentTarget.checked); void saveItem(item); }} /><span><strong>{item.label}</strong><small>{item.hint}</small></span></label>
          {#if fieldErrors[item.key]}<p class="error" role="alert">{fieldErrors[item.key]}</p>{/if}
        </article>
      {:else}
        {@render numberSetting(item)}
      {/if}
    {/each}
  </Section>
  </div>
  {#if groups.limits.length || groups.bot.length}
    <details class="advanced"><summary>Advanced</summary>
      {#each configLoaded ? [...groups.limits, ...groups.bot] : [] as item (item.key)}
        {#if item.type === 'boolean'}
          <article class="setting-row">
            <label class="toggle"><input type="checkbox" checked={drafts[item.key] === true} disabled={savingKey === item.key} aria-label={item.label} onchange={(event) => { setDraft(item.key, event.currentTarget.checked); void saveItem(item); }} /><span><strong>{item.label}</strong><small>{item.hint}</small></span></label>
            {#if fieldErrors[item.key]}<p class="error" role="alert">{fieldErrors[item.key]}</p>{/if}
            {#if savedMessages[item.key]}<p class="saved" role="status">{savedMessages[item.key]}</p>{/if}

          </article>
        {:else}
          {@render numberSetting(item)}
          {/if}
      {/each}
      {#if !configLoaded}<div class="loading-list" role="status"><i class="visually-hidden">Loading</i><span></span><span></span></div>{/if}
    </details>
  {/if}
  {#if saveStatus}<p class="saved" role="status">{saveStatus}</p>{/if}
  <div id="model-types" class="settings-anchor" data-settings-anchor><TypesCard /></div>
  <div id="display" class="settings-anchor" data-settings-anchor><Section title="Appearance">
    <h3 class="choice-heading">App icon</h3>
    <div class="choices icon-choices" role="radiogroup" aria-label="App icon">
      {#each iconOptions as icon (icon.id)}
        <button type="button" class="tile" role="radio" tabindex={selectedIcon === icon.id ? 0 : -1} aria-checked={selectedIcon === icon.id} data-icon={icon.id} onclick={() => chooseIcon(icon.id)} onkeydown={(event) => onChoiceKeydown(event, iconOptions.map((option) => option.id), chooseIcon)}>
          <img src={icon.id === 'dark' ? '/icons/dark/icon-192.png' : '/icon-192.png'} alt="" />
          <span class="name">{icon.name}</span>
        </button>
      {/each}
    </div>
    {#if iconError}<p class="error" role="alert">{iconError}</p>{/if}
    {#if typeof navigator !== 'undefined' && /iPhone|iPad|iPod/.test(navigator.userAgent)}<p class="note">On iPhone, remove and re-add the web app to update its home-screen icon.</p>{/if}
    <h3 class="choice-heading">Theme</h3>
    <div class="choices" role="radiogroup" aria-label="Theme">
      {#each themes as theme (theme.mode)}
        <button type="button" class="tile theme" role="radio" tabindex={themeMode === theme.mode ? 0 : -1} aria-checked={themeMode === theme.mode} data-theme-mode={theme.mode} onclick={() => chooseTheme(theme.mode)} onkeydown={(event) => onChoiceKeydown(event, themes.map((option) => option.mode), chooseTheme)}>
          <span class="name">{theme.label}</span>
        </button>
      {/each}
    </div>
  </Section></div>
  <div id="review" class="settings-anchor" data-settings-anchor><Section title="Daily session review">
    <p class="note first">Reviews new local agent sessions each day and records session metrics and findings.</p>
    {#if !sweep && !sweepError}<div class="loading-sweep" role="status"><i class="visually-hidden">Loading</i><span></span><span></span><span></span><span></span></div>{/if}
    {#if sweep}
      <dl class="sweep-status">
        <div><dt>State</dt><dd>{sweep.failures.length ? 'Completed with errors' : sweep.state}</dd></div>
        <div><dt>Last run</dt><dd>{displayTime(sweep.last_run_at)}</dd></div>
        <div><dt>Next run</dt><dd>{displayTime(sweep.next_run_at)}</dd></div>
        <div><dt>Sessions seen</dt><dd>{sweep.counts.sessions_seen ?? 0}</dd></div>
        <div><dt>Analyzed</dt><dd>{sweep.counts.analyzed ?? 0}</dd></div>
        <div><dt>Skipped</dt><dd>{sweep.counts.skipped ?? 0}</dd></div>
        <div><dt>Findings recorded</dt><dd>{sweep.counts.friction_added ?? 0}</dd></div>
        <div><dt>Failures</dt><dd>{sweep.failures.length}</dd></div>
      </dl>
      {#if sweep.failures.length}
        <p class="note">These sessions could not be reviewed. Check each session's logs or retry with Run now after fixing the reported issue.</p>
        <ul class="sweep-failures" aria-label="Session review failures">
          {#each sweep.failures as failure}<li>{String(failure.error ?? failure.repo ?? JSON.stringify(failure))}</li>{/each}
        </ul>
      {/if}
      {#if sweep.digest}
        <div class="sweep-digest">
          <h3>Daily digest {sweep.digest.date ? '· ' + sweep.digest.date : ''}</h3>
          <p>{sweep.digest.text}</p>
          {#if sweep.model_tokens !== null}<p class="note">Summary model tokens: {sweep.model_tokens}</p>{/if}
        </div>
      {/if}
      {#if sweep.summary_error}<p class="error" role="status">Optional summary unavailable: {sweep.summary_error}</p>{/if}
    {/if}
    {#if sweepError}<p class="error" role="alert">{sweepError}</p>{/if}
    <Button disabled={sweepRunning} onclick={runSweep}>{sweepRunning ? 'Reviewing…' : 'Run now'}</Button>
  </Section><MailSoakCard /></div>
  <div id="status" class="settings-anchor" data-settings-anchor><Section title="Status">
    <div class="status" aria-label="Status">
      {#if dashboardLoaded}<InfrastructureCard {infrastructure} /><OtherAgentsCard {agents} />
      {:else}<div class="loading-status" role="status"><i class="visually-hidden">Loading</i><span></span><span></span></div>{/if}
    </div>
  </Section></div>
</div>

<style>
  .status{display:grid;gap:var(--space-3)}
  .loading-list,.loading-status,.loading-sweep{display:grid;gap:var(--space-3);min-height:calc(var(--control-h) * 3 + var(--space-3) * 2)}
  .loading-list span,.loading-status span,.loading-sweep span{height:var(--control-h);border-radius:var(--radius-control);background:var(--surface-inset)}
  .loading-sweep{grid-template-columns:repeat(2,minmax(0,1fr));min-height:calc(var(--control-h) * 4 + var(--space-3) * 3)}
  .setting-list{display:grid;gap:var(--space-2)}
  .harness-row,.setting-row{display:grid;gap:var(--space-2);min-width:0;padding:var(--space-3) 0;border-bottom:var(--line) solid var(--border-subtle)}
  .harness-row:last-child,.setting-row:last-child{border-bottom:0;padding-bottom:0}
  .toggle,.number-setting{display:flex;align-items:center;gap:var(--space-3);min-width:0;min-height:var(--control-h)}
  .toggle{width:100%;cursor:pointer}
  .toggle input{box-sizing:border-box;width:20px;height:20px;flex:none;accent-color:var(--accent)}
  .toggle span,.number-setting span{display:grid;gap:var(--space-1);min-width:0}
  .toggle small,.number-setting small{color:var(--text-muted);font-size:var(--font-size-xs);overflow-wrap:anywhere}
  .number-setting{justify-content:space-between;flex-wrap:wrap}
  .number-setting input{box-sizing:border-box;width:min(100%,180px);min-height:var(--control-h);padding-inline:var(--space-3);border:var(--line) solid var(--border-control);border-radius:var(--radius-control);background:var(--surface-input);color:var(--text-body);font:inherit;font-size:max(var(--font-size-md),1rem)}
  .number-setting input[aria-invalid=true]{border-color:var(--status-blocked-fg)}
  .advanced{display:grid;gap:var(--space-2);padding:var(--space-3) var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1)}
  .advanced summary{min-height:var(--control-h);display:flex;align-items:center;color:var(--text-strong);font-weight:650;cursor:pointer}
  .checklist{display:grid;gap:var(--space-2);margin:0;padding:0;list-style:none}.checklist li{display:flex;align-items:flex-start;gap:var(--space-2);min-height:var(--control-h)}.checklist-marker{box-sizing:border-box;flex:none;width:14px;height:14px;margin-top:.35em;border:1.5px solid var(--text-muted);border-radius:50%}.checklist a{display:block;min-height:44px;padding-top:var(--space-1);color:var(--accent);overflow-wrap:anywhere}
  .checklist-loading .skeleton-marker,.checklist-loading .skeleton-line{display:block;border-radius:var(--radius-control);background:var(--surface-inset)}.checklist-loading .skeleton-marker{width:var(--space-4);height:var(--space-3)}.checklist-loading .skeleton-line{flex:1;height:var(--space-4)}
  .runner-status{display:grid;gap:var(--space-2);margin:0 0 var(--space-3)}.runner-status div{display:grid;gap:var(--space-1)}.runner-status dt{color:var(--text-muted);font-size:var(--font-size-xs)}.runner-status dd{display:grid;justify-items:start;gap:var(--space-1);margin:0;overflow-wrap:anywhere}.runner-status dd small{color:var(--text-muted)}
  .saved{margin:0;padding:var(--space-2) var(--space-3);border-radius:var(--radius-control);background:var(--surface-success);color:var(--text-success);font-size:var(--font-size-sm)}
  .sweep-status{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-2);margin:0 0 var(--space-3)}
  .sweep-status div{padding:var(--space-2);border-radius:var(--radius-control);background:var(--surface-0)}
  .sweep-status dt{color:var(--text-muted);font-size:var(--font-size-xs)}
  .sweep-status dd{margin:var(--space-1) 0 0;color:var(--text-strong);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .sweep-failures{margin:0 0 var(--space-3);padding-left:var(--space-5);color:var(--status-blocked-fg);font-size:var(--font-size-sm)}
  .sweep-digest{margin:0 0 var(--space-3);padding:var(--space-3);border-radius:var(--radius-control);background:var(--surface-0);white-space:pre-line}
  .sweep-digest h3{margin:0 0 var(--space-2);font-size:var(--font-size-sm);color:var(--text-strong)}
  .sweep-digest p{margin:0;color:var(--text-body);font-size:var(--font-size-sm)}
  .note.first{margin-top:0;margin-bottom:var(--space-3)}
  .stack{display:grid;gap:var(--space-4)}
  :global(.stack[data-active-section] > *){display:none}
  :global(.stack[data-active-section] > p.saved){display:block}
  :global(.stack[data-active-section="harnesses"] > #harnesses){display:block}
  :global(.stack[data-active-section="runner"] > #first-run),:global(.stack[data-active-section="runner"] > #runner){display:block}
  :global(.stack[data-active-section="runner"] > #runner .section>header),:global(.stack[data-active-section="harnesses"] > #harnesses .section>header),:global(.stack[data-active-section="status"] > #status .section>header),:global(.stack[data-active-section="review"] > #review .section>header){display:none}
  :global(.stack[data-active-section="runner"] > .advanced){display:grid}
  :global(.stack[data-active-section="role-types"] > #role-types){display:grid;gap:var(--space-4)}
  :global(.stack[data-active-section="role-types"] > #role-types .section>header){display:none}
  :global(.stack[data-active-section="model-types"] > #model-types .section>header),:global(.stack[data-active-section="display"] > #display .section>header){display:none}
  :global(.stack[data-active-section="model-types"] > #model-types){display:block}
  :global(.stack[data-active-section="display"] > #display){display:block}
  :global(.stack[data-active-section="review"] > #review){display:grid;gap:16px}
  :global(.stack[data-active-section="status"] > #status){display:block}
  .settings-anchor{min-width:0;scroll-margin-top:calc(var(--topbar-height-mobile-safe) + var(--space-3))}
  @media(min-width:900px){.settings-anchor{scroll-margin-top:calc(var(--topbar-height-desktop-safe) + var(--space-3))}}
  .choices{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-2)}
  .icon-choices{grid-template-columns:repeat(2,minmax(0,1fr))}.icon-choices img{width:64px;height:64px;object-fit:contain}.choice-heading{margin:var(--space-3) 0 var(--space-2);font-size:var(--font-size-sm);color:var(--text-strong)}
  .tile{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--space-2);min-height:var(--control-h);min-width:0;padding:var(--space-3) var(--space-2);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-0);color:var(--text-body);cursor:pointer}
  .tile[aria-checked=true]{border-color:var(--accent);background:var(--surface-selected);color:var(--accent);box-shadow:inset 0 0 0 var(--selected-edge) var(--accent)}
  .name{font-size:var(--font-size-sm);font-weight:650;text-align:center;overflow-wrap:anywhere}
  .note{margin:var(--space-3) 0 0;color:var(--text-muted);font-size:var(--font-size-xs)}
  .error{margin:var(--space-2) 0 0;color:var(--status-blocked-fg);font-size:var(--font-size-sm);overflow-wrap:anywhere}
</style>
