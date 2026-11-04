<script lang="ts">
  import BackButton from './BackButton.svelte';
  let {
    title,
    subtitle = '',
    iconPath,
    menuExpanded = false,
    newChat = false,
    hideWordmark = false,
    singleLineTitle = false,
    backHref,
    backLabel = 'Back',
  }: {
    title: string;
    subtitle?: string;
    iconPath: string;
    menuExpanded?: boolean;
    newChat?: boolean;
    hideWordmark?: boolean;
    singleLineTitle?: boolean;
    backHref?: string;
    backLabel?: string;
  } = $props();
</script>

<header class="app-header" class:hide-wordmark={hideWordmark}>
  <div class="side left">
    {#if backHref}<BackButton href={backHref} label={backLabel} />{/if}
    <button class="menu-button" type="button" aria-label="Open menu" aria-haspopup="dialog" aria-expanded={menuExpanded} onclick={() => window.dispatchEvent(new Event('runner:open-menu'))}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
    </button>
    <a class="wordmark" href="/" aria-label="Varde home"><img src={iconPath} alt="" /><span>Varde</span></a>
  </div>
  <div class="title-group"><h1 class="title" class:single-line={singleLineTitle} title={title}>{title}</h1>{#if subtitle}<span class="subtitle" title={subtitle}>{subtitle}</span>{/if}</div>
  <div class="side right">
    {#if newChat}<a class="action" href="/new-item" aria-label="New conversation" title="New conversation"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></a>
    {/if}
  </div>
</header>

<style>
  .app-header{box-sizing:border-box;min-height:calc(60px + env(safe-area-inset-top));position:sticky;top:0;z-index:20;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr) minmax(0,1fr);align-items:center;column-gap:8px;padding:env(safe-area-inset-top) max(16px,env(safe-area-inset-right)) 0 max(16px,env(safe-area-inset-left));background:var(--cf-panel);border-bottom:1px solid var(--cf-line);font-family:system-ui,-apple-system,sans-serif;color:var(--cf-text)}
  .side{display:flex;align-items:center;gap:4px;min-width:0}.left{grid-column:1;grid-row:1}.right{grid-column:3;grid-row:1;justify-content:flex-end}.menu-button{display:grid;place-items:center;flex:none;width:44px;height:44px;padding:0;border:1px solid var(--cf-line);border-radius:50%;background:var(--cf-soft);color:var(--cf-text);cursor:pointer}.menu-button svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.menu-button:focus-visible,.action:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
  .wordmark{display:flex;align-items:center;gap:4px;min-width:0;min-height:44px;color:var(--cf-text);font-size:14px;font-weight:740;text-decoration:none}.wordmark img{width:23px;height:23px;flex:none}.wordmark span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.title-group{grid-column:2;grid-row:1;display:grid;justify-items:center;min-width:0;max-width:100%;text-align:center}.title{margin:0;min-width:0;max-width:100%;overflow-wrap:anywhere;font-size:16px;line-height:1.25;letter-spacing:-.02em}.subtitle{max-width:min(100%,64ch);color:var(--cf-muted);font-size:11px;line-height:1.25;text-wrap:balance}
  .action{display:grid;place-items:center;flex:none;width:44px;height:44px;border-radius:50%;background:var(--cf-soft);color:var(--cf-text);text-decoration:none}.action svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  .title.single-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;overflow-wrap:normal}
  @media(min-width:761px){.app-header{padding-left:max(32px,env(safe-area-inset-left));padding-right:max(32px,env(safe-area-inset-right))}}
  @media(max-width:760px){.app-header.hide-wordmark .wordmark{display:none}}
  .action:focus-visible{outline-color:var(--cf-text)}
</style>
