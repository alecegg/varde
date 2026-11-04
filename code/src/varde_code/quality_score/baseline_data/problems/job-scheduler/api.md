# job-scheduler API

Solution file: `solution.py` / `solution.ts` / `Solution.cs`. Errors: Python `ValueError`, TypeScript `Error`, C# any exception.

- Python: `Job(id: str, duration: int, priority: int = 0, deps: tuple = ())`, `Run(id, start, end)` (attributes), `run_jobs(jobs: list[Job], limit: int) -> list[Run]`.
- TypeScript: `export function runJobs(jobs: {id, duration, priority, deps}[], limit): {id, start, end}[]` (plain objects).
- C#: `record Job(string Id, int Duration, int Priority, string[] Deps)`, `record Run(string Id, int Start, int End)`, `static class Scheduler { static List<Run> RunJobs(List<Job> jobs, int limit) }`.
