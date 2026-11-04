---
topic: varde-docs/spec-delegation
version: 1
summary: Delegate independent spec domains to builders and brief them
---

Delegate only domains with independent source and output paths, to at most
three active builders that each write one document under
`<knowledge>/specs/`. Brief each with:

- Resolved absolute `<working>` and `<knowledge>` paths, used without
  re-resolving.
- Whether `varde` is on PATH.
- The domain, its changed files, the output path, and the spec format reference.
