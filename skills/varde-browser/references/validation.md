# Browser validation evidence

Use this reference after the target is defined and before running checks.

## Evidence record

Report these fields for every validation run:

```text
Capability: available | degraded
Target: <url and route>
Viewport: <width>x<height>
Tool: <detected tool or unavailable>
Passed: <checks with evidence>
Failed: <checks with evidence>
Degraded: <checks that could not run and why>
Artifacts: <screenshots, logs, or traces, or none>
```

For each screenshot or log, include the requested URL, viewport, and check
name. Prefer small, named artifacts.

## Read-only checks

If the probe reports `capability=available`, choose checks that match the
request:

- page load and route resolution
- visible content and layout at the requested viewport
- console errors and failed network requests
- keyboard focus and accessible names
- responsive overflow or clipped content

Do not submit forms, change account data, publish content, deploy code, or
delete state. Stop before authentication when no authorization was supplied.

## Degraded result

If no supported tool is available, the probe prints:

```text
capability=degraded
reason=No supported browser tooling found on PATH.
guidance=Install supported tooling separately, then rerun; no browser evidence was collected.
```

Copy those fields into the run report. Do not infer browser behavior from
source inspection, screenshots supplied by others, or a successful HTTP fetch.
