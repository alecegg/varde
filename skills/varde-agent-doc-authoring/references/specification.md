# Skill file requirements

## Frontmatter

| Field | Required | Constraints |
|---|---|---|
| `name` | Yes | 1–64 ASCII lowercase letters and digits, with single internal hyphens only; must match the parent directory. |
| `description` | Yes | Non-empty, max 1024 characters. Say what the skill does, when to use it, and relevant trigger terms. |
| `allowed-tools` | No | Space-separated pre-approved tools, e.g. `Bash(git:*) Bash(jq:*) Read`. Experimental; support varies by client. |

Optional: `license`, `compatibility` (≤500 chars), `metadata` (string→string map).
Mapping keys must be unique, including nested mappings; YAML merge overrides remain valid.

## Description wording

Lead with the user's outcome verbs; end with `Not for <nearest sibling task>`
when a sibling skill overlaps. Include indirect phrasings users use, and
distinguish nearby tasks that should not match. Write it as one double-quoted
physical-line YAML value — some loaders parse frontmatter line by line and
miss folded or multiline descriptions.

## Validation

The bundled [validator](../scripts/validate-frontmatter.py) parses YAML and
checks frontmatter constraints from this skill's directory (see `SKILL.md`,
Author or revise step 3, for the sandbox fallback). Pass several paths or an installed skills
root to check many; add `--json` for machine-readable output.
