<script lang="ts">
  import { Dialog as BitsDialog } from 'bits-ui';
  import './chatTokens.css';
  let {
    open,
    onClose,
    iconPath = '/favicon.svg',
  }: {
    open: boolean;
    onClose: () => void;
    iconPath?: string;
  } = $props();

  function closeIfDismissed(nextOpen: boolean) {
    if (!nextOpen) onClose();
  }

</script>

<BitsDialog.Root {open} onOpenChange={closeIfDismissed}>
  <BitsDialog.Portal>
    <BitsDialog.Overlay class="menu-scrim" />
    <BitsDialog.Content class="menu-panel" aria-describedby={undefined}>
      <div class="menu-heading">
        <BitsDialog.Title class="menu-title"><img src={iconPath} alt="" />Varde</BitsDialog.Title>
        <BitsDialog.Close class="menu-close" aria-label="Close menu"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></BitsDialog.Close>
      </div>

      <nav class="menu-links" aria-label="Main menu">
        <a href="/" onclick={onClose}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H8l-4 4zM8 9h8m-8 4h5" /></svg>Conversations</a>
        <a href="/plans" onclick={onClose}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5m-18 5 9 5 9-5" /></svg>Plans</a>
        <a href="/settings" onclick={onClose}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4m0-12.8L17 7M7 17l-1.4 1.4" /></svg>Settings</a>
      </nav>
    </BitsDialog.Content>
  </BitsDialog.Portal>
</BitsDialog.Root>

<style>
  :global(.menu-scrim) {
    position: fixed;
    z-index: 1000;
    inset: 0;
    background: #0007;
    animation: scrim-in 240ms ease-out;
  }

  :global(.menu-panel) {
    position: fixed;
    z-index: 1001;
    inset: 0 auto 0 0;
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    width: min(320px, 88vw);
    height: 100dvh;
    padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    border: 0;
    border-radius: 0 20px 20px 0;
    outline: none;
    background: var(--cf-panel);
    color: var(--cf-text);
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 17px;
    line-height: 1.4;
    animation: sheet-in 240ms ease-out;
  }

  .menu-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 0 16px;
    font-weight: 700;
  }

  :global(.menu-title) {
    display:flex;align-items:center;gap:8px;
    margin: 0;
    font-size: 17px;
    font-weight: 700;
  }
  :global(.menu-title img){width:var(--icon-size);height:var(--icon-size)}

  :global(.menu-close) {
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border: 0;
    border-radius: 999px;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: 20px;
    cursor: pointer;
  }
  :global(.menu-close svg) { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }

  .menu-links {
    display: grid;
    gap: 4px;
  }

  .menu-links a {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 50px;
    padding: 0 14px;
    border-radius: 999px;
    color: inherit;
    font-weight: 620;
    text-decoration: none;
  }
  .menu-links svg{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;color:var(--cf-muted)}

  .menu-links a:hover,
  .menu-links a:focus-visible {
    background: var(--cf-soft);
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.menu-scrim), :global(.menu-panel) { animation: none; }
  }

</style>
