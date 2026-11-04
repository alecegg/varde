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
    _validate_limit(limit)
    _validate_jobs(jobs)
    runs = _Simulation(jobs, limit).run()
    return sorted(runs, key=lambda run: (run.start, run.id))


def _validate_limit(limit):
    if limit < 1:
        raise ValueError("limit must be at least 1")


def _validate_jobs(jobs):
    _reject_duplicate_ids(jobs)
    _reject_invalid_durations(jobs)
    _reject_unknown_dependencies(jobs)
    _reject_cycles(jobs)


def _reject_duplicate_ids(jobs):
    seen_ids = set()
    for job in jobs:
        if job.id in seen_ids:
            raise ValueError(f"duplicate job id: {job.id}")
        seen_ids.add(job.id)


def _reject_invalid_durations(jobs):
    for job in jobs:
        if job.duration < 1:
            raise ValueError(f"duration must be at least 1: {job.id}")


def _reject_unknown_dependencies(jobs):
    known_ids = {job.id for job in jobs}
    for job in jobs:
        unknown = set(job.deps) - known_ids
        if unknown:
            raise ValueError(
                f"job {job.id} has unknown dependencies: {sorted(unknown)}"
            )


def _reject_cycles(jobs):
    unresolved = {job.id: set(job.deps) for job in jobs}
    while unresolved:
        resolvable = [job_id for job_id, deps in unresolved.items() if not deps]
        if not resolvable:
            raise ValueError("dependency cycle detected")
        _resolve(unresolved, resolvable)


def _resolve(unresolved, resolved_ids):
    for job_id in resolved_ids:
        del unresolved[job_id]
    for deps in unresolved.values():
        deps.difference_update(resolved_ids)


class _Simulation:
    def __init__(self, jobs, limit):
        self.limit = limit
        self.clock = 0
        self.pending = {job.id: job for job in jobs}
        self.running = {}
        self.finished = set()
        self.runs = []

    def run(self):
        while self.pending or self.running:
            self._finish_due_jobs()
            self._start_ready_jobs()
            self._advance_to_next_finish()
        return self.runs

    def _finish_due_jobs(self):
        due_ids = [
            job_id
            for job_id, end in self.running.items()
            if end <= self.clock
        ]
        for job_id in due_ids:
            del self.running[job_id]
            self.finished.add(job_id)

    def _start_ready_jobs(self):
        for job in self._ready_jobs_by_precedence():
            if self._at_capacity():
                break
            self._start(job)

    def _ready_jobs_by_precedence(self):
        ready = [
            job for job in self.pending.values()
            if self._is_ready(job)
        ]
        return sorted(ready, key=lambda job: (-job.priority, job.id))

    def _is_ready(self, job):
        return set(job.deps) <= self.finished

    def _at_capacity(self):
        return len(self.running) >= self.limit

    def _start(self, job):
        end = self.clock + job.duration
        del self.pending[job.id]
        self.running[job.id] = end
        self.runs.append(Run(job.id, self.clock, end))

    def _advance_to_next_finish(self):
        if self.running:
            self.clock = min(self.running.values())
