from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: str
    duration: int
    priority: int = 0
    deps: tuple = ()


@dataclass(frozen=True)
class Run:
    id: str
    start: int
    end: int


def run_jobs(jobs, limit):
    if limit < 1:
        raise ValueError("limit must be at least 1")
    by_id = {job.id: job for job in jobs}
    if any(dep not in by_id for job in jobs for dep in job.deps):
        raise ValueError("unknown dependency")
    pending, done, running, runs, now = set(by_id), {}, [], [], 0
    while pending or running:
        for run in [r for r in running if r.end <= now]:
            running.remove(run)
            done[run.id] = run.end
        ready = sorted(
            (by_id[i] for i in pending if all(d in done for d in by_id[i].deps)),
            key=lambda j: (-j.priority, j.id),
        )
        for job in ready[: limit - len(running)]:
            run = Run(job.id, now, now + job.duration)
            running.append(run)
            runs.append(run)
            pending.discard(job.id)
        if not running and pending:
            raise ValueError("dependency cycle")
        if running:
            now = min(r.end for r in running)
    return sorted(runs, key=lambda r: (r.start, r.id))
