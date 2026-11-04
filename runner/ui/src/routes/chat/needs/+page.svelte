<script lang="ts">
  import ChatList from '../../../lib/chat/ChatList.svelte';
  import ChatHeader from '../../../lib/ChatHeader.svelte';
</script>

<div class="needs-page"><ChatHeader title="Needs action" subtitle="Items waiting for your response" /><ChatList needsOnly /></div>
<style>.needs-page{display:flex;flex:1;flex-direction:column;min-height:0;min-width:0}.needs-page :global(.chat-list){flex:1;min-height:0;overflow:auto}</style>
