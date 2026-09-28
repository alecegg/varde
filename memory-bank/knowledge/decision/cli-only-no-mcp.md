---
id: decision/cli-only-no-mcp
type: decision
status: accepted
generated:
  by: human:unspecified
  at: 2026-08-13T20:30:17.893Z
verified: []
paths: []
enriched_at_commit: null
_version: dea161ff9fdc7038f2b343754b62b631a87b33a7f2aa513af37d43d1e04b34d4
---

## What

varde-workflow is a CLI tool, not an MCP server. It has no MCP tool
surface.

## Why

Corrects an assumption carried over from HANDOFF.md's "CLI vs MCP-first
surface" framing — that question is resolved: CLI only.

## Constraints

- If MCP support is added later, it would be a separate, additive
  surface on top of the CLI's core operations, not a redesign of them.
