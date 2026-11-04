<!-- kind: reference -->
# Pull request body

Not part of the body. Follow these house rules:

- Use a conventional `type(scope): summary` title.
- Use no emojis.
- Read attribution from the active harness environment; do not invent an identity.

## Summary

State what changed and why. Link the plan or issue when one exists.

## Evidence

For each check, record:

- The command you ran.
- Its result.
- What it proves.

Link screenshots by path when useful.

## Merge Danger

Describe:

- Changed public APIs.
- Data or config migrations.
- Dependents and key impact edges.
- Hotspots touched.
- Rollout order and rollback.

Say `none found` only with what you checked. If unavailable, state `blast radius not measured: no index` or include the script's specific measurement error.
