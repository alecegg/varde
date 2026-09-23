# Write agent documents

## Use project evidence

Write from real project evidence. Use completed tasks, runbooks, schemas,
incidents, review comments, or code history. Record only corrections that the
repository does not make obvious. If no source exists, ask for one before
drafting a new skill.

For a project-specific workflow, prefer procedures over broad declarations.
State the default action. Explain the choice when judgment matters. Include
exact commands only for fragile operations.

## Keep reading focused

Skill metadata always loads. The `SKILL.md` body loads when the skill fires.
Scripts and references load only when the body asks for them.

- Keep `SKILL.md` as a run sheet. Aim below 5,000 tokens.
- Put detailed procedures, exhaustive tables, and long templates in local
  `references/`, `assets/`, or `scripts/` directories.
- Say exactly when to read every reference. A bare "see references" pointer is
  not enough.
- Keep references one level below the skill. Do not make another skill's local
  files a runtime dependency.
- Consolidate material always read in the same phase. Split material only when
  each branch has a distinct loading condition.

Scripts are preferable when they encode repeated parsing or validation. Agents
read their output, not their source. Give scripts a
non-interactive CLI, useful `--help`, structured stdout, diagnostics on stderr,
and meaningful exit codes.

## Write frontmatter and descriptions

Every skill needs a lowercase hyphenated `name` matching its directory and a
`description` under 1,024 characters. Read `specification.md` when changing
frontmatter or diagnosing validation failures.

The description triggers the skill; it is not product copy. Lead with the
user's likely request. Name the task and the situations where the skill helps.
Avoid repeated synonyms that describe the same branch.

Choose invocation deliberately:

- Model-invoked skills add their descriptions to every context. Use them when the
  agent must discover the skill itself.
- User-invoked skills add no description context. Use them for remembered, explicit
  commands that no other skill must invoke.

## Scope and content

Scope one coherent unit of work. Avoid tiny skills that must always compose and
broad skills that cannot trigger precisely.

Use a gotchas section for concrete, non-obvious corrections. Use a template for
literal output formats. Add a verification loop when repeated work needs the
same correction. Remove generic background, stale environment facts, and rigid
rules that current models can apply through judgment.

Phrase the desired action positively when possible. Keep prohibitions only for
hard safety boundaries, paired with the correct alternative.

Punctuate a bold lead term by what it is. A noun-phrase label takes a colon
(`**When relevant:**`, `**Keep vs. drop:**`) because the gloss completes the
label. A numbered step's imperative is a whole sentence and takes a period
(`**Run the scan.** Do not pass --apply at this stage.`). The period-on-a-label
form is a machine-writing tell, and it reads as a sentence the next clause
interrupts.

## Specialized references

- Read `optimizing-descriptions.md` when trigger quality needs measured tuning.
- Read `evaluating-skills.md` after a skill has stabilized and needs repeatable
  quality evaluation.
- Read `using-scripts.md` when adding or changing a bundled script.
