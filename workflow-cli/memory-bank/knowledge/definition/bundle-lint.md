---
slug: bundle-lint
type: definition
definition: >-
  A contradiction-aware health check over a Knowledge Bundle (and, when
  run in Vault-merged mode, across the Personal + Project Vault). Checks
  orphaned Concepts, broken links, duplicate aliases, coverage gaps, and
  semantic contradictions between Concepts. Modeled on pi-llm-wiki's
  `wiki_lint`; named to mirror cyano's `bundle_validate`. OKF v0.2
  conformance checks are optional and opt-in, run only via `lint --okf`;
  they are never part of the default (non-OKF) lint pass.
avoid:
  - wiki_lint
  - vault_lint
---
