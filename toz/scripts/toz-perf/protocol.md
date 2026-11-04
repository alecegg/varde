# Performance measurement protocol

Measurements run under ordinary load. The harness records `os.getloadavg()`
immediately before and after each row as `load_before` and `load_after`, plus
`lock_hold_s`; every measured run and every attempt stays in the results. Rows
are not delayed or repeated based on load. Reports show the load values beside
every table.

Measure Python rows in the same session. Hold the shared measurement lock for
the complete row, with the timer running inside the lock.
Use `toz/scripts/toz-perf/perf_run.py` to collect rows and `dev/scripts/with-lock.sh` to
own the lock. Its optional `VARDE_LOCK_TIMEOUT_S` and `VARDE_LOCK_DIR` settings
retain their existing behavior. Tests use a temporary lock directory.

For write measurements, keep the existing `ioreg` `Bytes (Write)` idle-floor
windows and subtract the matched idle floor as before. Do not substitute a
different disk counter.
