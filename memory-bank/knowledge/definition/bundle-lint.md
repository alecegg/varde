---
slug: bundle-lint
type: definition
definition: >-
  A contradiction-aware health check over a single Knowledge Bundle.
  Checks orphaned Concepts, broken links, missing `index.md` files
  (opt-in via `--require-index`), malformed concepts, and unreadable
  entries. Modeled on pi-llm-wiki's `wiki_lint`; named to mirror cyano's
  `bundle_validate`. Report-only: never blocks or rejects a bundle, never
  writes to disk.
avoid:
  - wiki_lint
  - vault_lint
---
