---
name: varde-docs
description: "Use this skill when README.md, docs/*.md, changelogs or release notes need refreshing against current code, or when domain specs under the knowledge store need regenerating from source."
recommends: [varde-doc-authoring, varde-build, varde-code, varde-learn]
---

# Maintain project documentation

Every text change gets an independent documentation-authoring review (`references/review-gates.md`).

## Choose the reference

| Document type | Read |
|---|---|
| User-facing: README.md, `docs/*.md`, CHANGELOGs, release notes, or another document a reader opens directly (`refresh`) | `references/refresh.md` |
| A generated domain specification under `<knowledge>/specs/` (`spec`) | `references/spec.md` |

## Gotchas

- Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess them.
