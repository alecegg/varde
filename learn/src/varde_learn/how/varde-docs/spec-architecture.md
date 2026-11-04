---
topic: varde-docs/spec-architecture
version: 1
summary: Decide whether the architecture spec needs a refresh
---

- If no sources are found, skip and say so. Never infer architecture from
  folder layout alone.
- Otherwise, leave the document byte-identical unless it needs a refresh.

Architecture sources:

- files declaring deployed units, their wiring, and package/workspace
  structure (infrastructure-as-code, deployment config, workspace manifests),
  including new declaration files outside old roots;
- every entrypoint or handler read to map units to domains.

Recompute their provenance and covered paths like a domain's.

Refresh architecture only when it is missing or stale, its declaration set
changed, or a domain was added or removed. Write
`<knowledge>/specs/architecture.md` with `domain: architecture` per the spec
format reference, and list it in the index.
