# Explain mode

Write a source-grounded explanation of a change or code area as one
self-contained HTML file (inline CSS, no external assets). If the user asks
for another format, answer in chat in that format instead.

## Resolve the target shape

| Target shape | Treat as |
|---|---|
| Git ref: branch name, commit range (`abc..def`), or PR reference (`pr/123`, `#123`) | a change explanation |
| Feature-area keyword (e.g. `authentication`) or file/directory path (e.g. `src/core/auth/`) | an area explanation |
| A set of named alternatives or a design question (e.g. "queue vs. pub/sub") | an options comparison |

A bare word that is both a git ref and a path or area is ambiguous: ask inline
as a numbered menu. Otherwise infer the shape and state it in one line.

## Workflow

1. **Explore the target.** Load `references/varde-code-cli.md` for unknown scope
   or several targets.
2. **Gather shape-specific context:** for a change, the diff (PR:
   `gh pr diff <n>`, else fetch `pull/<n>/head` and diff against the PR's
   base, not the current checkout); for an area, recent notable commits for
   Background; for options, the code each alternative would touch.
3. **Write the HTML** with the sections for the resolved shape below, to a
   path the user named or else
   `<working>/explanations/<YYYY-MM-DD>-<slug>.html` (resolved absolute
   `<working>`, short kebab-case `<slug>`), and tell the user the exact path.
## HTML output sections

Change or area shape:

| Section | Purpose |
|---|---|
| Background | Why it exists: the change's intent, or the area's `git log`. |
| Intuition | How it works: analogies, invariants. |
| Code (change) or How It Works (area) | Change: walk the hunks per file with affected callers. Area: key files, entry points, and data flow. |

Options shape:

| Section | Purpose |
|---|---|
| Options | Each named alternative, one paragraph. |
| Tradeoffs | Each alternative against shared project constraints. |
| Recommendation | One recommendation and what remains uncertain. |
