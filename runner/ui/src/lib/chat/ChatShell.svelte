<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import { page } from '$app/state';
  import MenuSheet from './MenuSheet.svelte';
  import DesktopChatSidebar from './DesktopChatSidebar.svelte';
  import AppHeader from './AppHeader.svelte';
  import { appIconPath, headerContextKey, headerTitle, type AppIconChoice, type HeaderContext } from './navHeader';

  let { children, chatUnread = false }: { children: () => any; chatUnread?: boolean } = $props();
  let menuOpen = $state(false);
  let selectedIcon = $state<AppIconChoice>('slate-bronze');
  const headerContext = $state<HeaderContext>({ iconPath: '/favicon.svg', menuExpanded: false, pageTitle: '', subtitle: '', singleLineTitle: false });
  setContext(headerContextKey, headerContext);
  $effect(() => {
    headerContext.iconPath = appIconPath(selectedIcon);
    headerContext.menuExpanded = menuOpen;
  });
  onMount(() => {
    const openMenu = () => { menuOpen = true; };
    window.addEventListener('runner:open-menu', openMenu);
    const updateIcon = (event: Event) => {
      const icon = (event as CustomEvent<AppIconChoice>).detail;
      if (icon === 'dark' || icon === 'slate-bronze') selectedIcon = icon;
    };
    window.addEventListener('runner:app-icon', updateIcon);
    fetch('/api/settings', { cache: 'no-store' }).then((response) => response.ok ? response.json() : null).then((settings) => {
      if (settings?.app_icon === 'dark' || settings?.app_icon === 'slate-bronze') selectedIcon = settings.app_icon;
    }).catch(() => {});
    const viewport = window.visualViewport;
    const updateViewport = () => {
      if (!viewport) return;
      const keyboardInset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
      document.documentElement.style.setProperty('--thread-viewport-height', `${viewport.height}px`);
      document.documentElement.style.setProperty('--thread-viewport-top', `${viewport.offsetTop}px`);
      document.documentElement.style.setProperty('--kb-inset', `${keyboardInset}px`);
    };
    viewport?.addEventListener('resize', updateViewport);
    viewport?.addEventListener('scroll', updateViewport);
    updateViewport();
    return () => {
      window.removeEventListener('runner:open-menu', openMenu);
      window.removeEventListener('runner:app-icon', updateIcon);
      viewport?.removeEventListener('resize', updateViewport);
      viewport?.removeEventListener('scroll', updateViewport);
      document.documentElement.style.removeProperty('--thread-viewport-height');
      document.documentElement.style.removeProperty('--thread-viewport-top');
      document.documentElement.style.removeProperty('--kb-inset');
    };
  });
  const landing = $derived(page.url.pathname === '/' || page.url.pathname === '/chat');
  const chatListRoute = $derived(landing || page.url.pathname === '/chat/needs');
  const settingsRoute = $derived(page.url.pathname.startsWith('/settings'));
  const threadRoute = $derived(page.url.pathname.startsWith('/thread/'));
  $effect(() => {
    if (!threadRoute) return;
    document.documentElement.classList.add('chat-thread-open');
    document.body.classList.add('chat-thread-open');
    return () => {
      document.documentElement.classList.remove('chat-thread-open');
      document.body.classList.remove('chat-thread-open');
    };
  });
  const title = $derived(headerTitle(page.url.pathname));
  function closeMenu() {
    menuOpen = false;
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.menu-button')?.focus({ preventScroll: true }));
  }
</script>

<svelte:head><title>Varde Runner · {title}</title></svelte:head>
<div class="chat-shell" class:landing class:chat-list-route={chatListRoute} class:thread-route={threadRoute} class:settings-route={settingsRoute} class:unread={chatUnread} class:menu-open={menuOpen}>
  <AppHeader title={headerContext.pageTitle || title} subtitle={headerContext.subtitle} iconPath={headerContext.iconPath} menuExpanded={menuOpen} newChat={landing} backHref={headerContext.backHref} backLabel={headerContext.backLabel} singleLineTitle={headerContext.singleLineTitle} hideWordmark />
  <MenuSheet open={menuOpen} onClose={closeMenu} iconPath={headerContext.iconPath} />
  <DesktopChatSidebar />
  <div class="shell-body">
    <main class="shell-content">
      {#if landing}<div class="landing-mobile">{@render children()}</div><div class="desktop-empty-state"><p>Select a conversation or start a new one</p><a href="/new-item">Start a new conversation</a></div>{:else}{@render children()}{/if}
    </main>
  </div>
</div>

<style>
  .chat-shell{min-height:100dvh;background:var(--cf-bg);color:var(--cf-text);font-family:system-ui,-apple-system,sans-serif;font-size:17px;line-height:1.4}
  .shell-content :global(h1),.shell-content :global(h2),.shell-content :global(h3),.shell-content :global([id]),.shell-content :global(.queued),.shell-content :global(.plan-title){scroll-margin-block-start:calc(var(--topbar-height-mobile-safe) + var(--space-3))}
  :global(html.chat-thread-open),:global(body.chat-thread-open){overflow:hidden;overscroll-behavior:none}
  .chat-shell.thread-route{position:fixed;z-index:1;inset-inline:0;top:var(--thread-viewport-top,0px);display:flex;width:100%;height:var(--thread-viewport-height,100dvh);min-height:0;flex-direction:column;overflow:hidden}
  :global(.chat-shell.menu-open .pinned-content){display:none}
  .shell-body{min-height:calc(100dvh - 202px)}.shell-content{min-width:0;padding:16px;overflow-wrap:anywhere}.landing .shell-body{min-height:100dvh}.landing .shell-content{padding:0}
  .thread-route .shell-body{display:flex;flex:1;min-height:0;height:0}
  .thread-route .shell-content{display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;height:100%;padding:0;overflow:hidden}
  .chat-list-route .shell-content{padding:0}
  @media(min-width:761px){.shell-body{display:flex}.shell-content{width:100%;padding:24px 32px}.thread-route .shell-content{padding:16px 32px 0}.landing .shell-body{display:block}.landing .shell-content{width:auto;margin:0;padding:0}}
  .desktop-empty-state{display:none;--focus:var(--cf-text)}
  @media(min-width:900px){.shell-content{flex:1 1 0%;width:auto!important;min-width:0;margin-left:320px!important;padding:0!important}:global(.chat-shell > .app-header){box-sizing:border-box;width:min(calc(100% - 320px),1120px);max-width:none;margin:0 0 16px calc(320px + max(0px,(100% - 320px - 1120px)/2));padding-right:32px;padding-left:32px;background:var(--cf-panel)}.chat-shell.thread-route{inset-inline:0;width:100%}.thread-route .shell-content{margin-left:320px!important;padding:16px 32px 0!important}.landing-mobile{display:none}.landing .shell-content .desktop-empty-state{display:grid;min-height:calc(var(--screen-h) - var(--topbar-height-desktop));place-content:center;justify-items:center;gap:var(--space-4);color:var(--cf-muted);text-align:center}.desktop-empty-state p{margin:0;font-size:var(--font-size-md)}.desktop-empty-state a{display:inline-flex;align-items:center;min-height:var(--control-h);padding:0 var(--space-4);border-radius:var(--radius-control);background:var(--accent);color:var(--surface-1);font-weight:600;text-decoration:none}.shell-body{min-height:var(--screen-h)}.thread-route .shell-body{min-height:0}.chat-shell :global(.menu-scrim){inset:0 0 0 320px}.chat-shell :global(.menu-panel){left:320px}:global(.chat-shell .app-header .wordmark){display:flex}:global(.app-header .side.left){justify-self:start}:global(.app-header .title-group){justify-self:center}}
  @media(min-width:1024px){.chat-shell:not(.landing) .shell-content{box-sizing:border-box;padding:24px 40px!important}:global(.chat-shell:not(.landing) .shell-content > :not(.chat-list)){box-sizing:border-box;width:min(100%,1120px);margin-inline:auto}}
  @media(max-width:899px){.chat-shell.settings-route .shell-content{padding:0}}
</style>
