<script lang="ts">
  import ChatThread from './chat/ChatThread.svelte';
  import { Button } from './ui';
</script>

<section class="home-thread" aria-label="Manager chat">
  <div class="thread-link"><Button href="/chat" variant="link">Open chat</Button></div>
  <ChatThread threadKey="main" compact />
</section>

<style>
  .home-thread{display:flex;flex-direction:column;height:300px;min-width:0;overflow:hidden;border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1)}
  .thread-link{display:flex;justify-content:flex-end;flex:none;min-height:40px;padding-inline:var(--space-2)}
  .home-thread :global(.chat-thread){flex:1;min-height:0}
  .home-thread :global(.chat-thread label.visually-hidden){font-size:0;line-height:0;white-space:normal;overflow-wrap:anywhere}
  @media(max-width:760px){.home-thread{height:280px}}
</style>
