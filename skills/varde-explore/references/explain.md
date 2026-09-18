# Explain mode

Produce a rich, source-grounded HTML explanation of either a code change or an
arbitrary code area. The output is a single self-contained HTML file (inline
CSS, no external assets) that a reader can open in a browser and understand
without prior context.

## Resolve the target shape

| Target shape | Treat as |
|---|---|
| Git ref — branch name, commit range (`abc..def`), or PR reference (`pr/123`, `#123`) | a change explanation |
| Feature-area keyword (e.g. `authentication`) or file/directory path (e.g. `src/core/auth/`) | an area explanation |

Confirm the resolved shape with the user when the target is ambiguous — ask
inline, in your message text, as a numbered menu (not a harness's native
question-prompt tool like Claude Code's `AskUserQuestion`, which renders outside
the continuous transcript).

## Workflow

1. **Resolve the shape.** Use the table above. Load `references/varde-code.md`
   if that CLI is on PATH, for call-graph and symbol-body operations that
   replace some of step 2's Grep/Glob/Read.
2. **Explore the target.** Use `Grep`/`Glob` to locate relevant symbols,
   imports, and references, then `Read` the actual source files directly —
   step 3 uses this context.
3. **Gather shape-specific context.** For a change explanation, resolve the git
   ref to a concrete diff and read the changed hunks — full procedure:
   `references/explain-diff.md`. For an area explanation, explore the keyword or
   path via `Grep`/`Glob`/`Read` plus `git log` for history — full procedure:
   `references/explain-section.md`.
4. **Write the HTML output.** Compose the four sections below into one
   self-contained file in the system temp directory (`$TMPDIR` if set, else
   `/tmp`), named `<YYYY-MM-DD>-<slug>.html` (`<slug>` a short kebab-case
   identifier derived from the target), inline CSS only — no external
   stylesheets, scripts, images, or fonts, so it renders offline from any
   machine. Write the file directly with `Write`/`Edit`. Tell the user the exact
   file path when done.
5. **Record lessons.** Invoke `varde-knowledge reflect`. It records friction
   from this skill and saves durable lessons — a handoff belongs at a
   session boundary, which this is not.

## HTML output sections

Fixed per shape — do not add or remove sections based on user preference at
invocation time.

### Background

Why this code exists, what problem it solves, and how it fits the wider system.
For an area explanation, ground this in the `git log` history pull; for a change
explanation, ground it in the change's intent.

### Intuition

Explain how the code works with analogies and key invariants. The reader should
be able to predict behavior before reading code.

### Code or How It Works

For a change explanation this is **Code** — walk through the change hunks file
by file: what each diff does, why, and the callers/callees the change affects.

For an area explanation this is **How It Works** — a structure walkthrough of
the key files, entry points, and data flows, using the symbols and references
found via `Grep`/`Glob`/`Read` up front.

### Quiz

5 multiple-choice questions that test the reader's understanding of the
explanation above, each with the correct answer and a one-line explanation of
why it is correct. Ground the questions in what the sections actually covered —
no trivia beyond the explanation.

## Gotchas

- HTML only — no other output formats.
