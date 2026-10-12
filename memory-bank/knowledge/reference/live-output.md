---
type: reference
status: active
title: "Live output contract"
description: Preview and capture behavior for tool output, including Codex integration.
---

# Live output contract

## Standard previews

- Captured previews print `toz: exit code N` before section indexes.
- This includes successful commands with `exit code 0`.
- Adjacent identical stderr lines collapse in previews only.
- Repeated signatures use a suffix such as `warning ×3`.
- Stored chunks and search results remain complete.

## Codex integration

Completed unified `exec_command` sessions use `PostToolUse` capture.
Oversized completed output becomes bounded context with a searchable handle.

Unfinished raw `write_stdin` polls remain unchanged by host limitation.
