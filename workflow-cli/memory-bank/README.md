# memory-bank/

Project memory uses plain Markdown and YAML configuration.
Direct editing remains supported when formats stay valid.

## Storage boundaries

- `knowledge/` contains durable, committed project knowledge.
- `config/` contains durable, committed workflow configuration.
- `working/` contains local plans, reviews, and evidence.
- `friction/` contains local observations awaiting possible promotion.

Personal knowledge belongs outside this repository entirely.

## Conventions

- Keep one Markdown document per stored artifact.
- Use YAML frontmatter for structured artifact metadata.
- Use kebab-case identifiers unless local formats differ.
- Preserve existing paths when updating durable knowledge.
- Never place secrets inside committed memory artifacts.

Read each store's local guidance before changing formats.
