<script lang="ts">
 import {Button,IconButton,Input,SearchInput,Select,Textarea,Checkbox,Badge,StatusMarker,Card,ListRow,DisclosureRow,GroupHeader,Field,Dialog,Tabs,EmptyState,PageHeader,SummaryStrip,FilterChip,OverflowMenu,Stack,Cluster,PinnedBar,keyboardSafe,Markdown,Section,Row,Evidence} from '../../lib/ui';
 import OtherAgentsCard from '../../lib/OtherAgentsCard.svelte';
 let selected=$state('one'),openId=$state<string|null>(null),reply=$state('');
 const buttonVariants=['primary','secondary','ghost','danger','link'] as const;
 const iconButtonVariants=['primary','secondary','ghost','danger'] as const;
 const badgeTones=['neutral','running','success','waiting','blocked','needs-input','idle'] as const;
 const statusTypes=['running','success','waiting','blocked','needs-input','idle'] as const;
 const catalogShot="data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='390' height='240'%3E%3Crect width='390' height='240' fill='%23888'/%3E%3C/svg%3E";
 function toggle(id:string){openId=openId===id?null:id}
</script>
<svelte:head><title>Component catalog</title></svelte:head>
{#snippet dialogTrigger(props: Record<string, unknown>)}<Button variant="secondary" {...props}>Open dialog</Button>{/snippet}
{#snippet panelOne()}Panel one{/snippet}{#snippet panelTwo()}Panel two{/snippet}
<main>
 <PageHeader title="Component catalog" description="Shared dashboard components" />
 <Card title="Actions"><Cluster>{#each buttonVariants as variant}<Button {variant} onclick={()=>{}}>{variant}</Button>{/each}{#each iconButtonVariants as variant}<IconButton label={`${variant} action`} {variant} disabled>{variant[0]}</IconButton>{/each}<Button disabled>Disabled</Button><Dialog title="Example dialog" description="Dialog description" trigger={dialogTrigger}><p>Dialog content</p></Dialog><OverflowMenu items={[{label:'Action',onclick:()=>{}}]} /></Cluster></Card>
 <Card title="Fields"><Stack><Field label="Field" hint="Helpful hint"><Input aria-label="Field input"/></Field><SearchInput aria-label="Search catalog" placeholder="Search"/><Select label="Select" value="one" options={[{value:'one',label:'One'}]}/><Textarea label="Textarea" id="catalog-textarea" placeholder="Write a reply"/><Checkbox label="Checkbox"/><Checkbox type="switch" label="Switch"/></Stack></Card>
 <Card title="Status and content"><Cluster>{#each badgeTones as tone}<Badge {tone}>{tone}</Badge>{/each}{#each statusTypes as status}<StatusMarker {status} label={status}/>{/each}</Cluster><ListRow selected unread>Selected unread row</ListRow><GroupHeader title="Active plans" count={2}/><DisclosureRow title="First expandable row" id="catalog-detail-1" open={openId==='first'} onToggle={()=>toggle('first')}>Details one</DisclosureRow><DisclosureRow title="Second expandable row" id="catalog-detail-2" open={openId==='second'} onToggle={()=>toggle('second')}>Details two</DisclosureRow><EmptyState title="Nothing here" description="A concise explanation."/></Card>
 <Card title="Navigation"><Tabs bind:value={selected} items={[{value:'one',label:'One',panel:panelOne},{value:'two',label:'Two',panel:panelTwo}]}/><SummaryStrip items={[{label:'Running',count:2,active:true},{label:'Blocked',count:1}]}/><FilterChip active>Active filter</FilterChip></Card>
 <Card title="Shared page patterns"><p>PageHeader opens a page; Section groups rows (tone default, attention for needs-user, quiet for running); Row is a link row with title, meta, chips and trailing actions; Markdown renders plan text as sanitised HTML.</p><Section title="Needs you" count={1} tone="attention"><Row href="/plans" title="Attention row" meta="plan-id">{#snippet chips()}<Badge tone="needs-input">needs-input</Badge>{/snippet}</Row></Section><Section title="Running" count={1} tone="quiet"><Row title="Quiet row" meta="plan-id">{#snippet chips()}<Badge tone="running">running</Badge>{/snippet}</Row></Section><Markdown text={'## Markdown heading\n\nA paragraph with **bold**, `code` and a [link](/plans).\n\n- first item\n- second item\n\n```\nblock code\n```\n\n<b>escaped</b>'}/></Card>
 <Card title="Evidence"><Evidence urlFor={()=>catalogShot} items={[{kind:'diff',caption:'Diff stat',text:' runner/ui/src/lib/mail/ThreadView.svelte | 24 ++++++\n 3 files changed, 61 insertions(+), 2 deletions(-)'},{kind:'shot',caption:'Thread at 390px'},{kind:'note',caption:'Builder note',text:'Approval card **ready**; see `T2.md`.'}]}/></Card>
 <OtherAgentsCard agents={[{id:'catalog-agent-1',title:'Catalog agent',status:'running'}]} />
 <Card title="Pinned reply demo"><form class="reply" use:keyboardSafe onsubmit={(event)=>event.preventDefault()}><Textarea bind:value={reply} label="Reply" id="catalog-reply" placeholder="Write a reply" onkeydown={(event)=>{if((event.metaKey||event.ctrlKey)&&event.key==='Enter')event.currentTarget.form?.requestSubmit()}}/><PinnedBar><Button type="submit">Send</Button></PinnedBar></form></Card>
</main>
<style>main{display:grid;gap:var(--space-4);max-width:var(--content-max);margin-inline:auto;padding:var(--space-4)}.reply{min-height:var(--screen-h);display:flex;flex-direction:column;justify-content:space-between}.reply :global(.pinned-bar){margin-top:auto}</style>
