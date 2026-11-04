---
topic: varde-build/measured-runs
version: 1
summary: Wrap long builds and tests; name the limiter of a measured result
---

Wrap long builds and tests in `scripts/measure-writes.sh run` and report its
`writes:` line. Before reporting a measured result:

- Name its limiter with run evidence.
- Rule out skipped, cached, or failed work.
- Give the run count and range.

Prefer compile-only checks for iteration when available.
