<!-- kind: reference -->
# Skill file requirements

## Frontmatter

| Field | Required | Constraints |
|---|---|---|
| `name` | Yes | Lowercase hyphenated; must match the parent directory. |
| `description` | Yes | Non-empty; see Description wording. |

## Description wording

The description must:

- be concrete and user-worded, leading with the user's outcome verbs;
- say when the skill applies, including indirect phrasings users use;
- distinguish nearby tasks, ending with `Not for <nearest sibling task>` when
  a sibling skill overlaps;
- be one double-quoted physical-line YAML value, because some loaders parse
  frontmatter line by line and miss folded or multiline descriptions.
