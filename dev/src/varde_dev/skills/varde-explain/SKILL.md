---
name: varde-explain
description: "Use this skill when the user wants to understand how a change (branch, commit range, PR) or a code area works, or asks for a page comparing named alternatives."
recommends: [varde-code, varde-plan, varde-build]
---

# Explain code

## Resolve the target

| Target | Treat as |
|---|---|
| Git ref: branch, commit range (`abc..def`), or PR (`pr/123`, `#123`) | Change explanation |
| Feature keyword or file/directory path | Area explanation |
| Named alternatives for an explicitly requested page | Options page |

If a bare word could be both a git ref and an area, ask inline with a numbered menu. Otherwise state the inferred shape.

## Answer in chat

- Ground the explanation in files read and cite `path:line`.
- A change explanation reflects the diff against its base (a PR: `gh pr diff <n>`).
- An area explanation reflects key files and recent notable commits.
- For structure questions, load `references/varde-code-cli.md` (shipped shared reference).

## Write a page

Write a page only when the user explicitly asks for a page, file or HTML.

- A named non-HTML format or a bare request to explain a diff stays in chat.
- Otherwise load `references/page.md`; the page is exported as a static file with `varde learn docs build`.

## Handoff

When the user asks to plan or build a change, start that work in the same turn.
