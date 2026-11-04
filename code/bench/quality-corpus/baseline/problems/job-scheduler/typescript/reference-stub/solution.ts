interface Job {
  id: string;
  duration: number;
  priority: number;
  deps: string[];
}

interface Run {
  id: string;
  start: number;
  end: number;
}

export function runJobs(jobs: Job[], limit: number): Run[] {
  if (limit < 1) throw new Error("limit must be at least 1");
  const byId = new Map(jobs.map((job) => [job.id, job]));
  if (jobs.some((job) => job.deps.some((dep) => !byId.has(dep)))) throw new Error("unknown dependency");
  const pending = new Set(byId.keys());
  const done = new Set<string>();
  let running: Run[] = [];
  const runs: Run[] = [];
  let now = 0;
  while (pending.size > 0 || running.length > 0) {
    for (const run of running.filter((r) => r.end <= now)) done.add(run.id);
    running = running.filter((r) => r.end > now);
    const ready = [...pending]
      .map((id) => byId.get(id)!)
      .filter((job) => job.deps.every((dep) => done.has(dep)))
      .sort((a, b) => b.priority - a.priority || (a.id < b.id ? -1 : 1));
    for (const job of ready.slice(0, limit - running.length)) {
      const run = { id: job.id, start: now, end: now + job.duration };
      running.push(run);
      runs.push(run);
      pending.delete(job.id);
    }
    if (running.length === 0 && pending.size > 0) throw new Error("dependency cycle");
    if (running.length > 0) now = Math.min(...running.map((r) => r.end));
  }
  return runs.sort((a, b) => a.start - b.start || (a.id < b.id ? -1 : 1));
}
