# The varde skills, in plain terms

A human-readable tour of the seven core skills in this directory: what each one is
for, what it actually does, and what it leaves behind on disk.

Skills are markdown instruction sets an agent loads on demand. Each is a
`SKILL.md` (the always-loaded entry point) plus a flat `references/` directory
the entry point pulls from selectively. You never name a mode — the agent reads
your request and picks the right reference.

| Skill | One line |
|---|---|
| `varde-explore` | Understand something before committing to it |
| `varde-change` | The change lifecycle: status → plan → build → verify |
| `varde-review` | Find problems in code, and optionally fix them |
| `varde-docs` | Keep README/docs and generated specs true to the code |
| `varde-knowledge` | Durable project memory, friction, and handoffs |
| `varde-prototype` | Throwaway mockups that answer a design question |
| `varde-agent-doc-authoring` | Write and audit agent-facing documents |

Optional packs add independent capabilities:

| Pack | Skill | Purpose |
|---|---|---|
| `diagnostics` | `varde-diagnose` | Analyze consent-bounded session transcripts |
| `browser` | `varde-browser` | Validate browser-backed workflows |
| `shipping` | `varde-release` | Prepare and verify authorized releases |

---

## The shape they share

A few conventions run through all seven, and knowing them makes each skill
easier to read.

**One entry point, one hop.** `SKILL.md` holds a routing table — "if the request
is X, read `references/y.md`" — and nothing else that isn't always true. The
reference it names is the whole procedure. References never chain more than one
level deep.

**Artifacts live under `memory-bank/` by default.** Work in flight goes in
`memory-bank/working/` (plans, reviews, prototypes, handoffs, friction). Durable knowledge
goes in `memory-bank/knowledge/` (notes, specs). Either directory can be
redirected per user — for one project or all of them — with
`varde-workflow paths set`; the setting lives in `~/.config/varde/paths.toml`,
never in the repo. Skill references therefore write these as `<working>/…` and
`<knowledge>/…`, resolved once per session via `varde-workflow paths --json`
(or `$VARDE_WORKING_DIR` / `$VARDE_KNOWLEDGE_DIR`, else the defaults). Whether
the directory is gitignored — or outside the repo entirely — changes behaviour
in several skills: a plan that isn't tracked can't travel through a git
worktree, so those runs stay in the current checkout.

**Optional CLIs, never required.** Two sibling tools sharpen several skills when
they're on `PATH`: `varde-code` for structural queries and `varde-workflow`
for knowledge and workflow artifacts. Skills describe fallback behavior when
either tool is unavailable.

**Worktree isolation is opt-in.** The default is always the current checkout, so
you can watch the diff and intervene. Isolation happens on request, or when a
concrete concurrent-edit risk exists. Whoever created the worktree owns merging
and cleaning it up.

**Questions are asked inline.** Numbered menus in the message text, one question
per turn, always with a recommendation — not a harness question widget, which
renders outside the transcript and separates the question from its answer in the
record.

**Everything ends with reflection.** Most skills close by invoking
`varde-knowledge reflect`. Mid-workflow that records friction and knowledge only;
at a genuine stopping point it also writes a handoff.

**Vendored, not shared.** `worktree.md` and `varde-code.md` appear inside several
skills as independent copies. That's deliberate: any skill must be installable on
its own. Edit the copy inside the skill you're working on.

---

## `varde-explore` — understand before committing

For open questions. Explicitly produces no plan and no production code.

**Explore** takes a design question or an uncertainty and answers it from
evidence: restate the question, read the actual sources, compare credible
alternatives against shared constraints, challenge assumptions against existing
project terminology, and summarise tradeoffs plus what's still unknown. The
whole output is understanding. Once your intent turns concrete it offers
`varde-change plan`, but only transitions if you say so.

**Explain** is the opposite posture — you know what you want explained, and you
want to keep the explanation. It resolves the target as either a *change* (a
branch, commit range, or PR) or an *area* (a keyword or path), then writes one
self-contained HTML file with four fixed sections:

- **Background** — why this code exists and where it sits
- **Intuition** — analogies and invariants, enough to predict behaviour
- **Code** / **How It Works** — a hunk-by-hunk walkthrough, or a structure tour
- **Quiz** — 5 multiple-choice questions grounded in what the doc covered

Inline CSS only, no external assets, so it opens offline anywhere.

---

## `varde-change` — the change lifecycle

The largest skill, and the spine of the system. Five modes.

### status

A read-only dashboard derived entirely from files on disk — there's no index and
no database. It globs `memory-bank/working/plans/*/plan.md` for active plans and
`memory-bank/working/handoffs/` for open handoffs, shows the top five of each,
and names exactly one mode to run next. It won't run that mode for you, and it
won't modify anything it reads.

### plan

A collaborative interview that grows a document. Its defining move: **`plan.md`
is created immediately, before any question is asked**, seeded with a best-guess
Problem and Solution, with every unknown routed into `## Open Questions` and
`## Assumptions`.

Not every unknown becomes a question. Two axes triage them: an unknown the agent
is confident about *and* whose cost of being wrong is contained becomes an
`## Assumptions` line at `confidence: high` and never costs a turn. Anything that
needs you, or that moves the plan split, the acceptance criteria, an external
contract, or the shape of the solution, becomes an `## Open Questions` entry.
When the axes disagree, impact wins.

Those questions then go **one per turn**, highest-value first, each asked inline
as a numbered menu with a recommendation. The assumptions are shown together as
a single batch before the exit check, so nothing is treated as accepted that you
never saw.

The document is the record rather than a queue left for you to find. It stays
open as a second channel the whole time — every turn re-reads it, so an edit you
make between turns is an answer like any other — and if you'd rather answer there
than in chat, saying so switches it to doc-driven mode and the questions stop.

The loop continues until Open Questions and Assumptions are both resolved, then
finalises: an acceptance-criteria review, a spec/AC consistency check, and a
batched review of close judgment calls before marking the plan ready.

Notable behaviours:

- **Deferred review findings surface here.** When the area under discussion has
  `Disposition: action-item` findings parked from an old review, they're raised
  during scope decisions — with staleness context (which branch, which date, has
  the area changed since). Surfaced for you to decide on, never auto-included.
- **Planning stops at the spec.** It produces exactly one file. No task files, no
  `## Tasks` section — decomposition is build's job, and splitting before the
  spec exists is a guess.
- **Readiness questions get a shortcut.** "Are we ready to build X?" grows the
  doc just far enough for Open Questions and Assumptions to be the answer.

### build

Runs one plan, tasks sequentially in dependency order, in one location. Wall
clock is deliberately not optimised — one task at a time keeps context clean and
usage predictable.

Entry is flexible: a named plan, a bare "build" (it discovers and presents
candidates), a free-text description (it writes a minimal plan and confirms it in
one turn), or a micro-change like "rename this label" that skips the machinery
entirely — make the edit, run the narrowest check, report.

Before implementing, it states a **posture**, selected per task:

| Posture | When |
|---|---|
| plan-execution | Default — no unusual risk profile |
| debug | A known bug or regression is the only goal |
| fix | Many files and many independent checks make checkpoints worthwhile |
| refactor | Behaviour-preserving, or `out_of_scope` forbids behaviour change |
| spike | The goal is answering a design question, not implementing it |

Then it decomposes the plan's spec and acceptance criteria into
`tasks/<task-id>.md` files and runs them. Each task: implement → `varde-review
simplify` over the uncommitted changes → run that task's `#### Verification`
block with bounded retry → typecheck and test → commit → mark `done` → derive the
next ready task. Retry exhaustion marks the task `blocked` and stops.

At the end: one report-only review pass, one fix round, then walk each plan-level
acceptance criterion and toggle `- [ ]` to `- [x]` — a criterion you can't confirm
is a blocker, not a silent pass.

Two load-bearing details worth knowing:

- Acceptance criteria are **plan-level only**. A task's own check is its
  `#### Verification` block; `status: done` means those checks passed.
- The closing fix round is invoked as `varde-review fix mode=build`. That
  parameter makes the fix pass attempt **every** finding rather than only the
  ones labelled `auto-fix`. Dropping it silently narrows what gets fixed.

### verify

Small and strictly read-only. Resolve the plan, read its criteria and completed
tasks, run the declared assertions and project checks, report what passed, what
failed, and what evidence wasn't available. It leaves acceptance checkboxes and
task statuses exactly as it found them, and recommends `build` when fixes turn
out to be needed.

### orchestrate

Runs a whole feature: a group plan (`shape: group`) whose children were created
by a plan-time split. It topologically sorts children by `depends_on`, then hands
each to `varde-change build` in turn, unattended. It adds no execution logic of
its own — build owns everything about running one plan.

Children are discovered by directory nesting, never from a frontmatter list.
Because a split makes them file-disjoint by construction, running them in order
needs no conflict resolution. A child that blocks or fails halts the run
immediately, leaving the location untouched for inspection. Success merges once,
at the end.

---

## `varde-review` — find problems, then decide what to do about them

Reporting is the default. Changing source requires you to ask.

### report

Never modifies a source file. It creates a review folder, detects the changed
sections, and reviews each one against the active categories, appending each
finding to its category file as it's found rather than batching at the end.

Breadth resolves from the request: a plain review gets the default three
(`CORRECTNESS`, `CODE`, `ARCHITECTURE`); a thorough review gets all ten filtered
by relevance; a named concern gets that single category.

The ten categories are `CORRECTNESS`, `CODE`, `ARCHITECTURE`, `SECURITY`,
`PERFORMANCE`, `OBSERVABILITY`, `READABILITY`, `RESILIENCE`, `DATA-INTEGRITY`,
and `API-DESIGN`. Each one states when it applies, what to look for, how to
calibrate severity, the check particular to it, and what a fix pass may not
auto-resolve. Three rules hold across all ten:

- **Read the full function or file, not the diff hunk** — most findings hinge on
  context outside the changed lines. Grep the call sites before judging blast
  radius.
- **A finding is a defect confirmed by reading real code.** "This could break" is
  not a finding.
- **A fix pass may auto-resolve only what mirrors a pattern already in the
  file.** Judgments about intended semantics, module boundaries, or concurrency
  escalate to a human.

### fix

Applies findings an earlier review wrote down. Its behaviour depends on who
called it:

| Caller | Automated pass covers | Human pass sees |
|---|---|---|
| A user, standalone | Only `Label: auto-fix` findings | Every `Label: triage` finding |
| `varde-change build` | **Every** finding, label ignored | Only what the escalation gate rejected |

The safety property that matters: **diff isolation is per-finding**. Before
applying a finding, the working-tree diff is recorded; on verification failure,
only that finding's own changes are reverted, and every earlier successful fix
stays. A whole-tree `git stash` would take the earlier fixes with it.

Afterwards it simplifies what it just touched, then creates one companion plan
per category with action items — pre-filled with each finding's title, location,
summary, and chosen solution as acceptance criteria. Those plans already have a
chosen solution and concrete criteria, so they go straight to `varde-change
build`; routing through `plan` first is only for genuinely underspecified ones.

### simplify

A clarity pass over just-changed lines, with no findings file and no review
folder. It computes changed-line ranges from `git diff` (defaulting to
uncommitted changes against `HEAD`), reads surrounding code for context, but
edits only within those ranges. New files are in scope in full.

It runs in the checkout that owns the diff and creates no worktree — a fresh
worktree starts clean and would have nothing to simplify.

Its principles are opinionated in a specific direction:

- **Readability beats fewer lines.** An abstraction that earns its place stays
  even if it looks small. A clever solution that's hard to follow is worse than
  the original.
- **Security and safety code stays** — auth checks, validation, sanitization,
  destructive-operation guards, accessibility affordances — *including* when a
  check looks dead in local context, because it may exist for a case outside the
  changed lines.
- **Never weaken a check to make something pass.** Restore the pre-change
  behaviour and flag it instead.
- Verification runs per file, and a failing run reverts that file's edits before
  moving on — the tree is never left worse than it started. A green run only
  proves anything if the tests actually cover the edited lines; if they don't,
  the report says so.

### scan

Two halves over `varde-code scan`'s rule definitions.

**Triage** treats every scan finding as a *candidate, not a verdict*. Findings are
grouped by `rule_id` (findings from one rule usually share a false-positive
pattern, so the first decision often resolves the group), and each is judged by
reading the actual code — the rule's `message` doesn't decide. Every finding
lands in exactly one of two buckets: needs a fix, or not a real issue with a
stated reason. There is no third "didn't look" bucket, which is why a large
finding count is a grouping problem rather than grounds for sampling. The closing
summary covers every finding from the scan, not just the fixed ones.

**Rule authoring** walks the format collaboratively — thresholds, severity, and
pattern shape are all judgment calls to confirm with you. It picks between
`pattern` rules (a syntactic shape in one file, matched per-file at scan time)
and `sql` rules (aggregates, thresholds, and graph relationships queried against
the persisted index), requires positive and negative `[[test]]` cases, and
validates with `varde-code test` before shipping.

If the same false positive keeps recurring, that's a rule problem — the skill
says to cross over to authoring rather than re-deciding the same finding forever.

---

## `varde-docs` — keep documentation true

### refresh

For README.md and `docs/*.md`. The key idea is two classes of content with
different rules:

- **Marker-declared sections** are auto-generated — read the source, write the
  replacement directly.
- **Everything else** — hand-authored sections in marked docs, and the entirety
  of unmarked docs — is compared against current code and surfaced as a proposed
  diff. Applied only on approval.

It runs in five phases: refresh any generated specs first (stale specs would
poison everything downstream), discover and classify every doc, auto-generate the
marker blocks, propose edits for approval, then verify by re-reading each edited
doc next to its source.

Because Phase 3 is interactive, this skill defaults *hard* to the current
checkout — a worktree would hide the very files you're being asked to approve.

### spec

Regenerates domain-first specifications under `memory-bank/knowledge/specs/`.
One reviewable document per domain, plus an architecture doc and an index. Every
spec is grounded in source actually read.

Scoping uses the `source_commit` recorded in the prior run's `index.md` to diff
only what changed, rather than rescanning the repo. Domains generate one at a
time by default; independent ones may be delegated, capped at three concurrent.
Orphan documents — those whose code no longer exists — are deleted, but only
from `specs/` and only when confirmed: *an unnecessary spec costs a little noise;
a wrongly deleted one loses work.*

---

## `varde-knowledge` — durable memory

### note

Reads and writes an OKF v0.2 Knowledge Bundle at `memory-bank/knowledge/`, laid
out type-first: `<type>/<slug>.md`, where type is `definition`, `decision`,
`pattern`, `reference`, or `spec`.

Search before reading — grep and glob to find candidates, then read whole files.
There's no partial fetch.

Three separate provenance facts are tracked deliberately:

| Field | Answers |
|---|---|
| `generated: {by, at}` | Who wrote the current content, and when |
| `verified: {by, at}` | Who reviewed and signed off — a human, not a dictation |
| `reconciled: {at, sha}` | When it was last checked against code, at what HEAD |

That third one is the one that matters most for a knowledge note, because it
answers "has the code moved since anyone last checked this?" A `reconciled.sha`
far behind `HEAD` is itself a staleness signal.

Checking notes against code runs slower and more carefully than friction
reconciliation, because a stale note is *wrong context a future agent will act
on*. The pass requires **evidence** — a drift claim must point at a changed
signature, a removed flag, a moved path, or the note stands — and **confirmation**
before rewriting anything someone else authored. Its endpoint is correct-in-place,
not deletion; retirement is `status: deprecated`, so links and history stay
resolvable.

A note about exposure, stated plainly in the skill: user-scoped knowledge lives
outside any repo, is cross-project by design, doesn't show in `git status`, and
**survives uninstalling the skill**. Notes quote source and paths from wherever
they were captured, so one written in a client repo can carry that repo's
internals into a cross-project store.

### reflect

Reviews finished work and routes anything worth keeping. Reflection itself writes
nothing — each record type has its own procedure.

| Type | When |
|---|---|
| Friction | An obstacle, workaround, bad guidance, or a proved-useful approach |
| Knowledge | A decision, finding, pattern, or definition another session needs |
| Handoff | Work is stopping or pausing, or a long run just ended |

How much gets considered depends on the caller. A session ending considers all
three. Another skill calling this at the end of its own run gets friction and
knowledge only — **a handoff belongs only at the outermost stopping point**, so a
child build inside an orchestrated run never writes one.

Order matters: knowledge before the handoff, and old items get rechecked before
the handoff too.

A separate distillation pass reviews recurring friction and proposes an
improvement. It never runs automatically and never applies a change without
approval.

---

## `varde-prototype` — throwaway answers to design questions

Two tracks, picked from the question:

**Visual** — "what should this look like?" Starts with 3 variants (cap 5) that
differ in layout, information hierarchy, and primary action, not just colour and
copy. Every variant file carries an identical fixed-position switcher bar linking
to its siblings with plain `<a href>` navigation, so flipping between them is a
real full-page view rather than a scaled preview. You pick a winner or a hybrid,
which seeds `v1.html`, then rounds proceed as Propose → Write → Show → Ask →
Revise, incrementing `v<N>.html` each time.

**Logic** — "does this state model feel right?" One file, `logic.html`, revised in
place with no version numbers. The logic lives in a pure module — reducer, state
machine, or plain functions, no DOM access — so it can move into production code
as-is when validated. The page around it is written in domain language, and
walkthrough scenarios deliberately stress the awkward cases: the tricky edge, the
action that should be illegal.

Rules across both tracks:

- **Delivery is always a plain HTML file on disk, path reported first.** A rich
  preview (Artifact, `mcp__visualize`) is an addition, never a replacement.
- One question per turn, inline, with a recommendation.
- Answer from project context first — grep for the design tokens or component
  library before falling back to conventions.
- The session ends only after an explicit affirmative to a closing confirmation.

Two nice touches: a hybrid pick ("the header from B with the sidebar from C") is
treated as *the real answer*, not a tie to break. And past 8 Visual rounds
without convergence, the skill suggests narrowing scope rather than grinding
more rounds.

Everything here is throwaway. No tests, no database, no framework, no
generalising beyond the question asked. Plans and production code belong to
`varde-change`.

---

## `varde-agent-doc-authoring` — the skill that maintains the skills

For writing and reviewing agent-facing documents: `SKILL.md`, `AGENTS.md`,
`CLAUDE.md`, skill references. Not for production code or user-facing docs.

Four task shapes, each with its own reference: author or revise a skill; review
one; improve triggering (how reliably a description fires on the right request);
or evaluate a mature skill with output evals. `references/vocabulary.md` is the
conceptual layer — read it when the question is *why a skill misfires* or *which
lever to pull*, rather than an editorial question.

That vocabulary is where this system's house style is defined, including the
failure modes the other skills are written to avoid:

- **Premature completion**, **duplication**, **sediment**, **sprawl**
- **No-op** — does this line change behaviour versus what the agent would do
  anyway?
- **Negation** — steering by prohibition backfires, because naming the forbidden
  behaviour makes it *more* available in context, not less. Prompt the positive.
- **Pruning discipline** — delete the whole sentence rather than trimming words
  from it.

Supporting guidance covers frontmatter requirements, progressive disclosure's
three load stages, bundled-script conventions, and writing descriptions that
trigger accurately (with a train/validation split so you don't overfit to your
own eval queries).

It ships a frontmatter validator: `uv run scripts/validate-frontmatter.py <dir>`.

---

## Installing

`./install.sh` copies the seven core skills into `~/.claude/skills/`. Flags: `-d` for
another runtime directory (opencode, codex, and pi all keep their own), `-s` for
an explicit subset, `-f` to force, `--yes` to approve removal of retired
directories without prompting, and `--pack` for optional packs.

Documentation and install checks run against this directory:

- `check-refs.sh` — enforces the one-flat-level layout, single-line
  descriptions, and that every backticked reference path resolves to a real file
- `tests/catalogue-docs.sh`, `tests/consolidated-workflows.sh`,
  `tests/install-catalogue.sh` — keep the README, the installer catalogue, and
  the mode routing tables consistent with each other
