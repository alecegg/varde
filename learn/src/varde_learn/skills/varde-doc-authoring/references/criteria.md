<!-- kind: reference -->
# Agent document criteria

## Cut or keep

Keep an instruction only if the agent would likely fail without it. Prescribe only:

- structural contracts (paths, formats, CLI invocations, state transitions);
- safety boundaries;
- preferences the agent cannot infer.

Cut text whose cost (tokens times load frequency, tool calls, turns) exceeds its value; when cutting changes behavior, report cost, value, and a cheaper alternative. Leave deterministic work to a script or CLI flag.

## Evidence and scope

- Record only corrections the repository does not make obvious.
- Flag instructions specific to one environment (machine paths, permission
  grants, harness procedures, personal tools) for user review; never
  auto-fix. State what the tool needs and does, so any
  agent can act.

## Structure

- Keep parallel items to a word or phrase, and rule items to one or two short
  sentences.
- Put a conditional branch in its own section after the main path.
- Give each step of a procedure a numbered heading (`## 1. Verb object`) when
  it needs a content block; keep a short procedure as a numbered list.
  Numbered items inside a step are sub-steps; unnumbered headings and bullets
  are information.
- End every line-per-item entry with its punctuation, and put a blank line
  after a list.

## Wording

- State the desired action positively. Reserve prohibitions for hard
  boundaries and give the alternative; keep a step-specific gotcha beside its
  step.
- Name mechanisms concretely: "an agent with a clean context", not "an
  independent reviewer".
- Keep every line specific enough to stay unambiguous; accuracy outranks
  brevity.

## Prompt anti-patterns

Each is a check, not a ban.

- **verification ritual:** a step that only confirms another (a re-read); delete it or fold its check into the verified step.
- **mandatory procedure:** a required sequence over work the agent can judge.
  Keep the goal and any hard gate; drop the `must`.
- **stale example:** a sample that no longer matches the tool; rerun and
  update, or delete.
- **contradictory rule:** two lines that disagree, or a rule its own exception
  cancels; keep one and state its condition.
