# Explain mode

Write a source-grounded HTML explanation of either a code change or a code area.
The output is one self-contained HTML file with inline CSS and no external
assets. A reader can open it in a browser without prior context.

## Resolve the target shape

| Target shape | Treat as |
|---|---|
| Git ref — branch name, commit range (`abc..def`), or PR reference (`pr/123`, `#123`) | a change explanation |
| Feature-area keyword (e.g. `authentication`) or file/directory path (e.g. `src/core/auth/`) | an area explanation |

If the target is ambiguous, ask the user to choose. Ask inline in your message
as a numbered menu. Do not use a harness's native question-prompt tool like
Claude Code's `AskUserQuestion`, which renders outside the continuous transcript.

## Workflow

1. **Resolve the shape.** Use the table above. Load
   `references/varde-code.md` for unknown scope, relationships, or several
   related targets. Read one known target directly. Use `get_symbol` only for
   one exact symbol inside a large file.
2. **Explore the target.** Use structural discovery only when step 1 selected
   it. Batch related lookups. Then read the required source content. Keep this
   context for step 3.
3. **Gather shape-specific context.** For a change explanation, resolve the git
   ref to a concrete diff and read the changed hunks. Follow
   `references/explain-diff.md`. For an area explanation, explore the keyword or
   path with `Grep`/`Glob`/`Read` and `git log`. Follow
   `references/explain-section.md`.
4. **Write the HTML output.** Write the four sections below into one
   self-contained file in the system temp directory (`$TMPDIR` if set, else
   `/tmp`). Name it `<YYYY-MM-DD>-<slug>.html`, where `<slug>` is a short
   kebab-case identifier derived from the target. Use inline CSS only. Do not
   use external stylesheets, scripts, images, or fonts, so the file renders
   offline from any machine. Write the file directly with `Write`/`Edit`. Tell
   the user the exact file path when done.
5. **Record lessons.** Invoke `varde-knowledge reflect`. It records friction
   from this skill and saves durable lessons. Do not create a handoff here. Create
   one only at a session boundary.

## HTML output sections

Use these four sections for every target. Do not add or remove sections because
of user preference.

### Background

Why this code exists, what problem it solves, and how it fits the wider system.
For an area explanation, ground this in the `git log` history pull; for a change
explanation, ground it in the change's intent.

### Intuition

Explain how the code works with analogies and key invariants. The reader should
be able to predict behavior before reading code.

### Code or How It Works

For a change explanation, call this section **Code**. Walk through the change
hunks file by file: what each diff does, why, and which callers/callees it
affects.

For an area explanation, call this section **How It Works**. Walk through the
key files, entry points, and data flows using the symbols and references found
with `Grep`/`Glob`/`Read` above.

### Quiz

Write 5 multiple-choice questions about the explanation above. Include the
correct answer and one line explaining why it is correct for each. Base the
questions on the covered sections. Do not add trivia beyond the explanation.

## Gotchas

- HTML only — no other output formats.
