<script lang="ts">
  import { getContext } from 'svelte';
  import { headerContextKey, type HeaderContext } from './chat/navHeader';
  let { title, subtitle = '', backHref = '/chat', backLabel = 'Back to chats', singleLineTitle = false }: { title: string; subtitle?: string; backHref?: string; backLabel?: string; singleLineTitle?: boolean } = $props();
  const header = getContext<HeaderContext>(headerContextKey);
  $effect(() => {
    header.pageTitle = title;
    header.subtitle = subtitle;
    header.backHref = backHref;
    header.backLabel = backLabel;
    header.singleLineTitle = singleLineTitle;
    return () => {
      header.pageTitle = '';
      header.subtitle = '';
      header.backHref = undefined;
      header.backLabel = undefined;
      header.singleLineTitle = false;
    };
  });
</script>
