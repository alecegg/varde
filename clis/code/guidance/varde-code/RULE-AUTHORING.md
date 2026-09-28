# Rule authoring

Create rules collaboratively because thresholds affect product behavior.

1. Collect concrete matching and non-matching examples.
2. Choose `pattern` for single-file syntax shapes.
3. Choose `sql` for aggregates or cross-file relationships.
4. Fill required identifiers, severity, and message fields.
5. Confirm thresholds, strings, and remediation wording.
6. Add positive and negative self-tests.
7. Validate the rule pack before repository scanning.

Use repository scope for project-specific conventions:

```text
<repo>/.varde-code/rules/<rule-id>.toml
```

Use user scope only for reusable personal rules:

```text
~/.config/varde-code/rules/<rule-id>.toml
```

Validate and inspect provenance:

```bash
varde-code rules test --json '{"rulesDir":"<rules-directory>"}'
varde-code rules list --json '{"repoRoot":"<repo>"}'
```

Read `RULE-FORMAT.md` before writing TOML fields.
