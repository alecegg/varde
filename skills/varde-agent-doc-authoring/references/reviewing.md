# Supplementary agent document checks

Use these checks to support the Review process in `SKILL.md`, or for a scoped
final pass after authoring. They apply to skills, agent guidance, and references.
Check contradictions and broken behavior as well as cut candidates. Weigh
failure risk against existing model, harness, and authoritative rules.

## When it applies

- Is the description concrete, user-worded, and specific about when it applies?
- Is model invocation worth its permanent description cost?
- Is the scope one coherent task?
- Does every tool in `allowed-tools` appear in the body?

## Loading and references

- Does the root contain only always-needed instructions?
- Does every conditional reference have an explicit load condition?
- Are files read together consolidated into one phase reference?
- Is any rule duplicated across sections instead of pointing to one
  authoritative location?
- Is this environment fact likely to become stale, and does the document need it?
- Fix fan-out by merging files, not by shortening prose.

## Instruction quality

- Would the agent likely fail without each instruction, with generic or
  replaceable rules removed? If an instruction's effect is consequential but
  unclear, compare a small prompt set with and without it and replace vague
  direction with an observable action or criterion.
- Is there a clear default where several methods could work, with hard rules
  reserved for fragile or destructive operations?
- Is the desired action stated positively, with concrete gotchas inline and
  easy to find?
- Do repeated outputs have a template or validator?

## Token economy

For substantive wording or loading changes, measure affected files with `wc -w`;
use the target model's tokenizer for token estimates when available.

- Does a paragraph enumerate cases a table or list would carry in fewer words?
- Does a sentence open with wind-up instead of its verb or condition?
- Does an explanation justify a rule the agent would follow without it?
- Does a triad spelled out three times collapse into one leading word?
- Is any line now short enough to be ambiguous? Accuracy outranks brevity.

For substantive wording or loading edits, re-measure and report the word delta.
For small fixes, briefly explain the concrete benefit instead.

## Workflow checks

Workflow skills (`workflow-skills.md`): the dispatch table names the real
discovery mechanism; one imperative action per step.
