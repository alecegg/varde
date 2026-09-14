# Agent Skills specification (agentskills.io)

## Directory structure

```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...
```

## Frontmatter fields

| Field           | Required | Constraints |
| --------------- | -------- | ----------- |
| `name`          | Yes      | Max 64 chars. Lowercase unicode alphanumeric + hyphens only. Must not start/end with hyphen or contain `--`. Must match the parent directory name. |
| `description`   | Yes      | Max 1024 chars, non-empty. What the skill does *and* when to use it, with keywords the agent will match against. |
| `license`       | No       | License name or reference to a bundled license file. |
| `compatibility` | No       | Max 500 chars. Environment requirements (product, system packages, network access). Most skills don't need it. |
| `metadata`      | No       | Arbitrary string->string map for client-specific properties. Use reasonably unique keys. |
| `allowed-tools` | No       | Space-separated pre-approved tools, e.g. `Bash(git:*) Bash(jq:*) Read`. Experimental — support varies by client. |

Invalid `name` examples: `PDF-Processing` (uppercase), `-pdf` (leading hyphen), `pdf--processing` (consecutive hyphens).

## Body content

No format restrictions after the frontmatter — but the whole file loads into context once the skill activates, so keep it lean (see main SKILL.md). Recommended sections: step-by-step instructions, input/output examples, common edge cases.

## Progressive disclosure (the three load stages)

1. **Metadata (~100 tokens)** — `name` + `description` loaded for *every* skill at startup, always in context.
2. **Instructions (<5000 tokens recommended)** — full `SKILL.md` body loads only once the skill activates.
3. **Resources (as needed)** — `scripts/`, `references/`, `assets/` files load only when the instructions tell the agent to open them.

Keep `SKILL.md` under 500 lines. Move detail to separate files and reference them with relative paths from the skill root, one level deep — avoid chains of references pointing to other references.

## Validation

The `skills-ref` reference library checks frontmatter validity and naming conventions:

```bash
skills-ref validate ./my-skill
```

This skill also bundles its own validator (no extra install, works offline): [`scripts/validate-frontmatter.py`](../scripts/validate-frontmatter.py). It parses the frontmatter as real YAML rather than eyeballing it, so it catches the failure mode that slips past manual review — an unquoted `: ` inside a plain scalar (e.g. `description: does X: does Y`), which is valid-looking Markdown but invalid YAML and breaks the skill at load time in strict parsers.

```bash
uv run scripts/validate-frontmatter.py ./my-skill              # one skill
uv run scripts/validate-frontmatter.py ~/.pi/agent/skills       # a whole installed skills root
uv run scripts/validate-frontmatter.py --json ./my-skill        # machine-readable
```
