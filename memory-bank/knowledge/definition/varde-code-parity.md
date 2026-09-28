---
slug: varde-code-parity
type: definition
definition: >-
  For the varde-code Rust port: parity means the Rust extractor covers
  everything the current TS extractor covers, but is free to add new
  fields or precision the TS version didn't have — a superset, not a
  byte-identical match. Downstream TS consumers may need updates to
  handle the richer output.
avoid:
  - byte-identical parity
---
