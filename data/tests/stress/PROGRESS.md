# Stress notes

## Hook latency

The opt-in live-shaped fixture creates 3,067 messages, 32,744 historical
deliveries, a reader at the start, and three new unread messages. Five fresh
subprocess open-plus-claim samples on 2026-10-24 had medians: files 64.4 ms
(62.5-70.2), SQLite 49.7 ms (47.4-58.4), mirror-files 65.9 ms (61.8-70.3),
and mirror-sqlite 48.1 ms (44.5-55.3). All measured modes were below the 70 ms
hook ceiling. cProfile showed the files and mirror-files paths make the same
history-related calls, with no extra mirror-side history scan. Each files path
made four message parse calls (one batch plus three row checks). SQLite uses the
reader/message/event delivery index rather than materializing delivery history.
The fixture is generated and does not depend on a live inbox copy.

## Cutover under load

The flip-under-writer-and-hook-reader-load test runs in the default tier and
exercises mirror-files to mirror-sqlite and back while workers are active, then
verifies claims, acknowledgements, and both stores.

## Default tier

On 2026-10-24, `uv run pytest data/tests/stress -q` passed: 7 passed, 1 opt-in
timing skip in 8.04 seconds, below the 20-second target. The production-size
timing uses `VARDE_STRESS_LIVE_SIZE=1`; the default tier keeps its short runtime.
The crash test uses readiness after a seed append, deterministic randomized kill
timing, observed completed appends, and an interrupted 400-row transaction
checked for all-or-nothing persistence.
