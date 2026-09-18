# Improve skill descriptions

Agents load every skill's `name` and `description` at startup. They read the
full `SKILL.md` only when a task matches. A vague description misses tasks. A
broad one runs too often. A one-step task may not need a skill at all.

## Writing principles

- **Imperative phrasing**: "Use this skill when..." not "This skill does...". The agent is deciding whether to act.
- **User intent, not implementation**: describe what the user is trying to achieve, since that's what gets matched against.
- **Be pushy**: explicitly list contexts where it applies, including when the user doesn't name the domain directly ("even if they don't mention 'CSV'").
- **Concise**: a few sentences to a short paragraph. Hard limit is 1024 characters.

Before/after:
```yaml
# Before
description: Process CSV files.

# After
description: "Analyze CSV and tabular data files — compute summary statistics, add derived columns, generate charts, and clean messy data. Use this skill when the user has a CSV, TSV, or Excel file and wants to explore, transform, or visualize the data, even if they don't explicitly mention \"CSV\" or \"analysis.\""
```

Keep the description on **one physical line**, double-quoted. Do not use a YAML
folded scalar (`description: >`) or any other multi-line form: some harnesses
parse frontmatter with a line-based regex rather than a YAML parser, so they
show the literal `>` as the whole description and the skill looks empty in the
skill list.

## Testing trigger accuracy with eval queries

Build ~20 realistic prompts labeled `should_trigger: true/false` (8-10 each):

```json
[
  { "query": "I've got a spreadsheet in ~/data/q4_results.xlsx with revenue in col C and expenses in col D — can you add a profit margin column and highlight anything under 10%?", "should_trigger": true },
  { "query": "whats the quickest way to convert this json file to yaml", "should_trigger": false }
]
```

Run the set with `scripts/run-evals.sh <skill-name> <queries.json> [--runs N]`
from this skill's directory: it sends each query, records whether the skill
fired, and reports accuracy against the labels. `--runs N` repeats each query so
a flaky trigger is visible rather than averaged away. This is the triggering
counterpart to `scripts/run-output-evals.sh`, which measures output quality
(`references/evaluating-skills.md`).

- **Should-trigger**: vary phrasing (formal/casual/typos), explicitness (naming the domain vs. describing the need), detail level, and task complexity. The most useful ones are where the skill would help but the connection isn't obvious — if the query already restates the skill, any description would pass.
- **Should-not-trigger**: use *near-misses* that share keywords/concepts but need something different (e.g. "update formulas in my Excel budget" for a CSV-analysis skill), not obviously irrelevant prompts ("write a fibonacci function") — those test nothing.
- Include realistic noise: file paths, personal context ("my manager asked..."), specific details, casual language/typos.

Run each query 3x (nondeterminism), compute a trigger rate. Should-trigger passes if rate > 0.5; should-not-trigger passes if rate < 0.5. Script structure:

```bash
#!/bin/bash
QUERIES_FILE="${1:?Usage: $0 <queries.json>}"
SKILL_NAME="my-skill"
RUNS=3

check_triggered() {
  local query="$1"
  claude -p "$query" --output-format json 2>/dev/null \
    | jq -e --arg skill "$SKILL_NAME" \
      'any(.messages[].content[]; .type == "tool_use" and .name == "Skill" and .input.skill == $skill)' \
      > /dev/null 2>&1
}
```

## Train/validation split (avoid overfitting)

Split queries ~60% train / ~40% validation, proportional mix of positive/negative in each, shuffled once and kept fixed across iterations.

Loop:
1. Evaluate current description on both sets.
2. Identify train-set failures only (keep validation untouched during iteration).
3. Revise: if should-trigger queries fail, broaden scope/context; if should-not-trigger queries false-fire, add specificity about what the skill does *not* do. Don't chase literal keywords from failed queries (overfitting) — find the general concept instead. If stuck after several passes, try a structurally different description rather than incremental tweaks. Recheck the 1024-char limit.
4. Repeat until train queries pass or improvement plateaus (~5 iterations is usually enough).
5. Pick the iteration with the best *validation* pass rate — not necessarily the last one.

After finalizing, sanity-check with 5-10 fresh queries never used during optimization.
