<script lang="ts">
  let { rows = 3, card = false, class: className = '' }: { rows?: number; card?: boolean; class?: string } = $props();
</script>

<div class={`skeleton ${className}`} class:card style={`--skeleton-rows:${rows}`} role="status">
  <div class="visually-hidden">Loading</div>
  {#each Array.from({ length: rows }) as _}
    <span></span>
  {/each}
</div>

<style>
  .skeleton{display:grid;gap:12px;min-height:calc(var(--skeleton-rows) * (var(--skeleton-row-h, 44px) + 12px) + 32px);padding:16px}
  .skeleton.card{border:1px solid var(--border);border-radius:var(--radius-card);background:var(--surface-1)}
  .skeleton span{height:var(--skeleton-row-h, 44px);border-radius:8px;background:linear-gradient(90deg,var(--surface-inset),var(--surface-2,var(--surface-inset)),var(--surface-inset));background-size:200% 100%;animation:shimmer 1.4s ease-in-out infinite}
  @keyframes shimmer{to{background-position:-200% 0}}
  @media(prefers-reduced-motion:reduce){.skeleton span{animation:none}}
</style>
