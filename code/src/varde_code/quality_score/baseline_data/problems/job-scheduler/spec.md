# job-scheduler behaviour spec

A job has `id`, `duration` (>= 1 ticks), `priority` (higher runs first) and `deps` (ids that must finish first). `run_jobs(jobs, limit)` simulates from tick 0 and returns runs `(id, start, end)` sorted by start, then id. At each tick it finishes jobs whose end tick has been reached, then starts ready jobs (all deps finished) by priority descending, then id ascending, while fewer than `limit` jobs are running.

1. One job runs from 0 to its duration.
2. A job starts only when its dependencies have ended (a 2 ticks, b 3 ticks needing a: a 0-2, b 2-5).
3. Among ready jobs the higher priority starts first.
4. With limit 1 equal-priority jobs run one after another in id order.
5. With limit 2 and three 2-tick jobs, two start at 0 and the third at 2.
6. Equal priority ties break by id ascending.
7. A dependency cycle (including a job depending on itself) is an error.
8. An unknown dependency id or limit < 1 is an error.
