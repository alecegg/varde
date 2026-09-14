---
name: varde-explain
description: >
  TRIGGER: Create a rich self-contained HTML explanation of a code change or
  code area, grounded in direct source reading and grep/glob exploration.
  SKIP: Skip only when the user wants a normal code review, implementation,
  or plain-text explanation without an HTML artifact.
  Example phrases: "explain this diff as HTML" or "teach me this module".
---

## Purpose

Produce a rich, source-grounded HTML explanation of either a code change or
an arbitrary code area. The output is a single self-contained HTML file
(inline CSS, no external assets) that a reader can open in a browser and
understand without prior context.

Invocation: `/varde-explain <target> [mode=diff|section]`

## Entry point dispatch

| Target shape | Mode |
|---|---|
| Git ref — branch name, commit range (`abc..def`), or PR reference (`pr/123`, `#123`) | diff |
| Feature-area keyword (e.g. `authentication`) or file/directory path (e.g. `src/core/auth/`) | section |
| Explicit `mode=diff` or `mode=section` argument | overrides auto-detection |

Confirm the resolved mode with the user when the target shape is ambiguous — ask inline, in your message text, as a numbered menu (not a harness's native question-prompt tool like Claude Code's `AskUserQuestion`, which renders outside the continuous transcript).

## Workflow

1. **Resolve the mode.** Auto-detect diff vs section from the target shape
   per the dispatch table above; an explicit `mode=` argument always wins.
   Check once per session whether the `varde-code` CLI (an optional tool, installed on PATH) is available: run
   `command -v varde-code >/dev/null 2>&1`. If present, load
   `references/VARDE-CODE-CLI.md` for optional call-graph and symbol-body operations that can
   replace some of step 2's Grep/Glob/Read. If it isn't, ignore that file
   and use the plain workflow below as-is.
2. **Explore the target.** Use `Grep`/`Glob` to locate relevant symbols,
   imports, and references, then `Read` the actual source files directly —
   this proactive gathering step is what step 3's mode-specific procedure
   calls back into.
3. **Gather mode-specific context.** Diff mode resolves the git ref to a
   concrete diff and reads the changed hunks. Full procedure:
   `references/DIFF-MODE.md`. Section mode explores a keyword or path via
   `Grep`/`Glob`/`Read`, plus `git log` for history. Full procedure:
   `references/SECTION-MODE.md`.
4. **Write the HTML output.** Compose the four sections below into one
   self-contained file in the system temp directory (`$TMPDIR` if set, else
   `/tmp`), named `<YYYY-MM-DD>-<slug>.html` (`<slug>` a short
   kebab-case identifier derived from the target), inline CSS only — no
   external stylesheets, scripts, images, or fonts, so it renders offline
   from any machine. Write the file directly with `Write`/`Edit`. Tell the
   user the exact file path when done.
5. **Reflect and consolidate.** Invoke `varde-reflect source=varde-explain` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## HTML output sections

Fixed per mode — do not add or remove sections based on user preference at
invocation time.

### Background

Why this code exists, what problem it solves, and how it fits the wider
system. In section mode, ground this in the `git log` history pull; in diff
mode, ground it in the change's intent.

### Intuition

A mental model of how the code works — analogies, key invariants, the
"what you need to internalize" layer. The goal is that the reader can predict
behavior before reading any code.

### Code or How It Works

In diff mode this is **Code** — walk through the change hunks file by file:
what each diff does, why, and the callers/callees the change affects.

In section mode this is **How It Works** — a structure walkthrough of the key
files, entry points, and data flows, using the symbols and references found
via `Grep`/`Glob`/`Read` up front.

### Quiz

5 multiple-choice questions that test the reader's understanding of the
explanation above, each with the correct answer and a one-line explanation of
why it is correct. Ground the questions in what the sections actually covered —
no trivia beyond the explanation.

## Gotchas

- HTML only — no other output formats.
