<!-- kind: reference -->
# Skill criteria

## One task

- Keep a skill to one coherent task: not too small to use alone, not too broad
  to select precisely.

## Prescribe contracts, leave judgment

Prescribe only structural contracts (folder layout, file paths, output formats,
CLI invocations, state transitions), safety boundaries (destructive,
irreversible, or outward-facing actions), and stated preferences. Skip what
the agent can infer.

Otherwise give the agent autonomy:

- Give exact commands only for fragile operations.

## How versus what

WHAT is an end state, validation, contract (above), or safety boundary; HOW
orders or guides the work toward an outcome. Test a line by deleting it: if a
capable agent still reaches and validates the outcome, it is HOW.

Start every write, trim, or rebuild from the no-how baseline: outcomes and
validation only, over the whole requested skill set, with no cut line. Add HOW
back (as a topic or tool) only where a friction item, eval, or review finding
shows an agent failed without it.

## No cross-skill routing

Body, references, and description name no other skill ("Not for X", "escalate
to Y"). Exempt: `varde-orchestrate`, `varde-swarm` (they may name what they
coordinate), and frontmatter `requires`/`recommends`. `varde learn check` warns (`skill-refs`).

## Optimize each item

Every item, and everything the checker flags, earns its cost in one pass:

- its value exceeds the cost of reading it (tokens times load frequency, plus maintenance) and following it (tool calls, turns, subagents, reruns, time). When cost far exceeds value but cutting changes behavior, report cost, value, and a cheaper alternative;
- it does not restate a default or repeat a rule another file owns (point to it). It omits rationale the agent does not need, edge-case guards, and script or CLI internals;
- deterministic work is a bundled script or CLI flag, with one line naming its skill-root-relative invocation and what to do with its result.

## Scripts and length checks

Give a bundled script with third-party dependencies a PEP 723 header and run
it with `uv run <skill-dir>/scripts/<name>.py`; run stdlib-only scripts with
`python3`.
`varde learn check <skill-dir-or-file>...` exits 1 only on errors. Optimize each
item it flags; a warning needs a reason in the review report, an error is a defect.

## Evals

An eval assertion states what the agent does or produces (behavior, artifacts,
commands, results). It never says that skill text or a file exists, is
mentioned, or was loaded, or that another skill owns the task. Good: "Runs the
dry run before applying sync". `varde learn check <skill-dir or SKILL.md>` warns
(`eval-content`); artifact shapes are fine.

## Loading and references

Make the entry file the outcomes, validations, and contracts every run needs.
Split references only:
- at a real branch of about 400 words or more across distinct routes or agents, or a conditional path many runs skip.

Other layout rules:

- keep each skill independently usable; a loaded reference belongs to that
  skill except for the declared cross-skill loads below;
- keep sequential content from one path in one file; state each load condition and prefix child filenames with the parent's name;
- merge other references and chains into their caller, keeping gates
  inline; state each rule once and point to it;
- keep each route a shallow tree (`SKILL.md` -> entry file -> leaf references).
  A leaf links to a sibling only to switch routes or for a conditional
  sub-step, and never forms a cycle. Shared rules load once from the entry file.

A file's kind:

- **Procedure:** loading it adds steps, decisions, or exits to the flow.
- **Reference:** loading it only shapes how a step already in progress is
  done. Sharing and frequency do not decide kind; if in doubt, leave it a
  procedure.

Reference checks:

- mark a reference with `<!-- kind: reference -->` as its first line (in a
  template, above the outer fence or the `Frontmatter:` line);
- map loading with `varde learn measure <skill> flow`. Treat chain findings as merge candidates,
  including single-caller findings when the caller is not a `SKILL.md` route.
  Treat any warning or defect as a route too big;
- name a backticked path after `skip` in the entry file, with its reason
  beside it, to drop it from that route's metrics;
- cross-skill load (orchestrating skills only): load another skill only with
  ``Load `<skill>`: use your skill tool, or read `../<skill>/SKILL.md` ``.
  Do so only if the citing skill lists it in `requires` or `recommends`.

## Ordered skill layout

For several invocation shapes, use an entry-point table whose cells name an
action. Use one numbered `## Workflow` per invocation type, with one primary
procedure per step. Keep literal templates inline or in `assets/`. End
`SKILL.md` with a short `## Gotchas` section of corrections needed whenever the
skill fires.

## Skill file requirements

### Frontmatter

| Field | Required | Constraints |
|---|---|---|
| `name` | Yes | 1-64 chars: lowercase letters, digits, single hyphens, none leading or trailing; must match the parent directory. |
| `description` | Yes | 1-1024 chars; see Description wording. |

`requires` and `recommends` are Varde extensions; `varde learn check` reports
these limits.

### Description wording

The description must:

- start `Use this skill when`, state user intent rather than
  implementation, and list the applicable contexts, including ones where the
  user names no domain;
- stay within a few sentences;
- contain no `Not for` or other negative clause and name no other skill;
  disambiguate with should-not-trigger near-miss queries in `evals/` instead;
- be one double-quoted physical-line YAML value, because some loaders parse
  frontmatter line by line and miss folded or multiline descriptions.
