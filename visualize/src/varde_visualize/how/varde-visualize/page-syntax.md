---
topic: varde-visualize/page-syntax
version: 1
summary: Write a page of ui statements, components and includes
---

- A page is markdown: a title, prose, then fences tagged `ui`. Each fence holds one or more statements.
- A statement is `<id> = <component>(<name>: <value>, ...)`; the id is `^[a-z][a-z0-9-]{0,47}$`, unique in the page.
- Values: strings, numbers, lists, `{...}`, `true`, `false`, `null` or an earlier id. `#` starts a comment.
- List components with `varde learn docs blocks`; read fields and an example with `varde learn docs blocks <type>`. `varde learn docs blocks --help` lists the recap and plan recipes.
- Example, "p50 and p95 latency before and after":

````
```ui
latency = chart(
  kind: "bar",
  labels: ["before", "after"],
  series: [{"name": "p50", "values": [120, 80]}, {"name": "p95", "values": [400, 210]}],
)
```
````

- Inputs (`choice`, `form`, `ranking`, `slider`, `comment`, `decision`) collect answers when served; an export shows them read-only.
- Include part of another markdown file in place with `plan-acceptance = include(source: "plan.md", select: "acceptance")`. `select` is `heading:<anchor>`, `task:<id>`, `frontmatter`, `acceptance` or `lines:<a>-<b>`.
- `varde learn check <page>` exit 1 prints one error per fault with its line; fix until it exits 0.
