<script lang="ts">
  let { href, title, preview }: { href: string; title: string; preview: string } = $props();
</script>

<a class="action" {href}>
  <strong>{title}</strong>
  <span>{preview}</span>
</a>

<style>
  .action{display:grid;gap:var(--space-1);min-width:0;padding:var(--space-3) var(--space-4);border:var(--line) solid var(--border);border-radius:var(--radius-card);background:var(--surface-1);color:var(--text-body);text-decoration:none}
  .action strong{color:var(--text-strong);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .action span{color:var(--text-muted);font-size:var(--font-size-sm);overflow-wrap:anywhere}
  .action:focus-visible{outline:var(--focus-ring);outline-offset:2px}
</style>
