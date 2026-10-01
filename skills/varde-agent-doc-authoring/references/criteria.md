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

## Optimize each item

Answer these in order, in one pass, for every item and everything the checker
flags.

1. **Worth it?** Weigh its value against two costs:
   - reading it: tokens times load frequency, plus maintenance
   - following it: the work it makes the agent do (tool calls, turns,
     subagents, reruns, time)

   When following it costs far more
   than its value but cutting would change behavior, report it to the user
   as an execution-cost optimization with:
   - its cost
   - the value it buys
   - a cheaper alternative
2. **Cut it?** Cut or shorten it when it:
   - restates a default the agent follows unprompted;
   - spells out a method where the goal and a default suffice;
   - repeats a rule another file or step owns (point to it instead);
   - explains rationale the agent does not need to act;
   - guards an edge case with no evidence of failure;
   - describes internals of a script or CLI the agent only calls.
3. **Script it?** Move remaining deterministic work into a bundled script (PEP
   723 inline dependencies) or CLI flag: scope computation, output paging,
   snapshots, validation. Leave one line naming its skill-root-relative
   invocation and what to do with its result; give repeated outputs a
   template or validator.

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

## Length limits

Run bundled scripts as `uv run <this-skill-dir>/scripts/<name>.py`; in a
sandbox, prefix `UV_PYTHON_PREFERENCE=only-system`.
`check-length.py <skill-dir-or-file>...` exits 1 only on defects. Optimize
each item it flags: a warning needs a reason, an error is a defect.

## Loading and references

Make the entry file a run sheet of always-needed instructions.
Split references only:
- at a real branch of about 400 words or more across distinct routes or agents, or a conditional path many runs skip;
- keep sequential content from one path in one file; state each load condition and prefix child filenames with the parent's name.

Other layout rules:

- merge other references and chains into their caller, keeping short
  procedures and gates inline; state each rule once and point to it;
- keep each route a shallow tree (`SKILL.md` -> entry file -> leaf references);
  leaves never point to each other or back up, and shared rules load once from
  the entry file.

A file's kind:

- **Procedure:** loading it adds steps, decisions, or exits to the flow.
- **Reference:** loading it only shapes how a step already in progress is
  done. Sharing and frequency do not decide kind; if in doubt, leave it a
  procedure.

Reference checks:

- mark a reference with `<!-- kind: reference -->` as its first line (in a
  template, above the outer fence or the `Frontmatter:` line);
- map loading with `skill-flow.py`; treat chain and single-caller findings as
  merge candidates and any warning or defect as a route too big;
- name a backticked path after `skip` in the entry file to drop it from that
  route's metrics.

## Ordered skill layout

### Entry point dispatch

For several invocation shapes, add an entry-point table. Each cell names an
action (a discovery method, operation, or reference), not an outcome.

### Workflow

Use one numbered workflow per invocation type:

- one primary procedure per step, inline or in a reference.

Keep workflows scannable:

- keep literal templates inline or in `assets/`;
- end `SKILL.md` with a short `## Gotchas` section of concrete corrections
  needed whenever the skill fires;
- make completion observable, adding an explicit handoff only when later work
  repeatedly prompts early completion and evidence shows a handoff helps.

## Wording

- State the desired action positively. Reserve prohibitions for hard
  boundaries and give the alternative; keep a step-specific gotcha beside its
  step.
- Open sentences with the verb or condition, not wind-up.
- Name mechanisms concretely: "an agent with a clean context", not "an
  independent reviewer".
- Keep every line specific enough to stay unambiguous; accuracy outranks
  brevity.

## Measure changes

For substantive wording or loading edits, measure affected files with `wc -w`
before and after (or the target model's tokenizer) and report the delta. For
small fixes, state the concrete benefit instead.
