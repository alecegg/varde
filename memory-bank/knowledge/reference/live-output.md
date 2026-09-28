# Live output contract

## Standard previews

- Captured previews print `toz: exit code N` before section indexes.
- This includes successful commands with `exit code 0`.
- Adjacent identical stderr lines collapse in previews only.
- Repeated signatures use a suffix such as `warning ×3`.
- Stored chunks and search results remain complete.

## Interactive runs

Use `toz run --live -- <command>` for noisy or long-running processes.

- The command runs inside a controlling PTY.
- A handle prints before the child starts.
- Input, terminal signals, and window size forward to the child.
- Chunks commit incrementally and become searchable before completion.
- Text progress is rate-limited and capped at twenty summaries.
- Completion marks the capture and stores the final exit status.

The normal `toz run` path remains completion-only.

## Codex integration

Completed unified `exec_command` sessions use `PostToolUse` capture.
Oversized completed output becomes bounded context with a searchable handle.

Unfinished raw `write_stdin` polls remain unchanged by host limitation.
Start noisy development servers with `toz run --live` before polling.
