<!-- kind: reference -->
# Agent document criteria

## Prescribe contracts, leave judgment

Prescribe only:

- structural contracts: folder layout, file paths, output formats, CLI
  invocations, state transitions;
- safety boundaries: destructive, irreversible, or outward-facing actions;
- stated preferences the agent cannot infer.

Otherwise give the agent autonomy:

- Give exact commands only for fragile operations.
- Keep an instruction only if the agent would likely fail without it. When its
  effect is consequential but unclear, compare a small prompt set with and
  without it.

## Evidence and scope

- Record only corrections the repository does not make obvious.
- Keep a skill to one coherent task: not too small to use alone, not too broad
  to select precisely.
- Flag instructions specific to one environment (machine paths, permission
  grants, harness procedures, personal tools) for user review; never
  auto-fix. Prefer stating what the tool needs (access, inputs) and does, so any
  agent can act. The user may keep them.

## Optimize each item

Answer these in order, in one pass, for every item and everything the checker
flags.

1. **Worth it?** Weigh its value against two costs:
   - reading it: tokens times load frequency, plus maintenance
   - following it: the work it makes the agent do (tool calls, turns,
     subagents, reruns, time)

   When its cost far exceeds its value but cutting changes behavior, report
   the cost, value, and a cheaper alternative as an execution-cost optimization.
2. **Cut it?** Cut or shorten it when it:
   - restates a default the agent follows unprompted;
   - spells out a method where the goal and a default suffice;
   - repeats a rule another file or step owns (point to it instead);
   - explains rationale the agent does not need to act;
   - guards an edge case with no evidence of failure;
   - describes internals of a script or CLI the agent only calls.
3. **Script it?** Move remaining deterministic work into a bundled script or
   CLI flag: scope computation, output paging, snapshots, validation. Leave
   one line naming its skill-root-relative invocation and what to do with its
   result; give repeated outputs a template or validator.

## Structure

- Keep parallel items to a word or phrase, and rule items to one or two short
  sentences; a list of long sentences only moves the length.
- Put a conditional branch in its own section after the main path.
- Give each step of a procedure a numbered heading (`## 1. Verb object`) when
  it needs a content block; keep a short procedure as a numbered list.
  Numbered items inside a step are sub-steps; unnumbered headings and bullets
  are information.
- End every line-per-item entry with its punctuation, and put a blank line
  after a list.

## Scripts and length checks

Give a bundled script with third-party dependencies a PEP 723 header and run
it with `uv run <skill-dir>/scripts/<name>.py`; run stdlib-only scripts with
`python3`.
`varde doc lint <skill-dir-or-file>...` exits 1 only on errors. Optimize each
item it flags: a warning needs a reason, an error is a defect.

## Loading and references

Make the entry file a run sheet of always-needed instructions.
Split references only:
- at a real branch of about 400 words or more across distinct routes or agents, or a conditional path many runs skip.

Other layout rules:

- keep each skill independently usable; a loaded reference belongs to that
  skill except for the declared cross-skill loads below;
- keep sequential content from one path in one file; state each load condition and prefix child filenames with the parent's name;
- merge other references and chains into their caller, keeping short
  procedures and gates inline; state each rule once and point to it;
- keep each route a shallow tree (`SKILL.md` -> entry file -> leaf references);
  a leaf links to a sibling only to switch routes or for a conditional
  sub-step and never forms a cycle. Shared rules load once from the entry file.

A file's kind:

- **Procedure:** loading it adds steps, decisions, or exits to the flow.
- **Reference:** loading it only shapes how a step already in progress is
  done. Sharing and frequency do not decide kind; if in doubt, leave it a
  procedure.

Reference checks:

- mark a reference with `<!-- kind: reference -->` as its first line (in a
  template, above the outer fence or the `Frontmatter:` line);
- map loading with `varde doc flow`; treat chain findings as merge candidates
  (also single-caller findings when the caller is not a `SKILL.md` route) and
  any warning or defect as a route too big;
- name a backticked path after `skip` in the entry file, with its reason
  beside it, to drop it from that route's metrics;
- cross-skill load: load another skill only with
  ``Load `<skill>`: use your skill tool, or read `../<skill>/SKILL.md` ``,
  and only when the citing skill's frontmatter lists it in `requires` or
  `recommends`. The path is relative to the citing file (`../<skill>/SKILL.md`
  from a `SKILL.md`, `../../<skill>/SKILL.md` from a reference).
- a conditional "If `<skill>` is installed, load ..." needs no declared
  relation.

## Ordered skill layout

For several invocation shapes, use an entry-point table whose cells name an
action. Use one numbered `## Workflow` per invocation type, with one primary
procedure per step; keep literal templates inline or in `assets/`; end
`SKILL.md` with a short `## Gotchas` section of corrections needed whenever the
skill fires. Add a handoff only when evidence shows it prevents repeated early
completion.

## Wording

- State the desired action positively. Reserve prohibitions for hard
  boundaries and give the alternative; keep a step-specific gotcha beside its
  step.
- Open sentences with the verb or condition, not wind-up.
- Name mechanisms concretely: "an agent with a clean context", not "an
  independent reviewer".
- Keep every line specific enough to stay unambiguous; accuracy outranks
  brevity.

## Prompt anti-patterns

Each is a reviewable check, not a ban.

- **verification ritual:** a step that only confirms another step (a re-read, a
  recount). Delete it, or fold its check into the step it verifies.
- **emphasis booster:** `very`, `always`, `never`, `critical`, `IMPORTANT`
  adding no condition. Drop the word; keep the boundary it decorated.
- **mandatory procedure:** a required sequence over work the agent can judge.
  Keep the goal and any hard gate; drop the `must`.
- **stale example:** a sample that no longer matches the tool; rerun and
  update, or delete.
- **contradictory rule:** two lines that disagree, or a rule its own exception
  cancels; keep one and state its condition.

## Measure changes

For substantive skill edits, report affected routes' `varde doc flow` token
ranges before and after; for other documents, report the word-count or
tokenizer delta. For small fixes, state the concrete benefit.
