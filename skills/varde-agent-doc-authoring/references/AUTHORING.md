# Authoring agent documents

## Ground the document

Write from real project evidence. Use completed tasks, runbooks, schemas,
incidents, review comments, or code history. Capture corrections that a capable
agent would not infer from the repository. If no source exists, ask for one
before drafting a new skill.

For a project-specific workflow, prefer procedures over broad declarations.
State the default action, its rationale when judgment matters, and exact
commands only where the operation is fragile.

## Control loading cost

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

Scripts are preferable when they encode repeated parsing or validation. Their
output enters context, while their source stays on disk. Give scripts a
non-interactive CLI, useful `--help`, structured stdout, diagnostics on stderr,
and meaningful exit codes.

## Write frontmatter and descriptions

Every skill needs a lowercase hyphenated `name` matching its directory and a
`description` under 1,024 characters. Read `specification.md` when changing
frontmatter or diagnosing validation failures.

The description is a trigger signal, not product copy. Lead with the user's
likely request. Name the task shape and the contexts where the skill helps.
Avoid repeated synonyms that describe the same branch.

Choose invocation deliberately:

- Model-invoked skills pay permanent description context. Use them when the
  agent must discover the skill itself.
- User-invoked skills avoid that cost. Use them for remembered, explicit
  commands that no other skill must invoke.

## Scope and content

Scope one coherent unit of work. Avoid tiny skills that must always compose and
broad skills that cannot trigger precisely.

Use a gotchas section for concrete, non-obvious corrections. Use a template for
literal output formats. Use a verification loop where repeated corrections show
one is needed. Remove generic background, stale copies of environment facts,
and rigid rules that current models can apply through judgment.

Phrase the desired action positively when possible. Keep prohibitions only for
hard safety boundaries, paired with the correct alternative.

## Specialized references

- Read `optimizing-descriptions.md` when trigger quality needs measured tuning.
- Read `evaluating-skills.md` after a skill has stabilized and needs repeatable
  quality evaluation.
- Read `using-scripts.md` when adding or changing a bundled script.
