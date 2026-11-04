export interface Job {
  id: string;
  duration: number;
  priority?: number;
  deps?: readonly string[];
}

export interface Run {
  id: string;
  start: number;
  end: number;
}

interface SimulationState {
  started: Set<string>;
  finished: Set<string>;
  running: Run[];
  runs: Run[];
  tick: number;
}

export function runJobs(jobs: readonly Job[], limit: number): Run[] {
  assertValidLimit(limit);
  const jobsById = indexJobsById(jobs);
  assertPositiveDurations(jobs);
  assertDependenciesExist(jobs, jobsById);
  assertNoDependencyCycle(jobs, jobsById);

  return simulate(jobs, limit);
}

function assertValidLimit(limit: number): void {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error("limit must be a positive integer");
  }
}

function indexJobsById(jobs: readonly Job[]): Map<string, Job> {
  const jobsById = new Map<string, Job>();
  for (const job of jobs) {
    if (jobsById.has(job.id)) {
      throw new Error(`duplicate job id: ${job.id}`);
    }
    jobsById.set(job.id, job);
  }
  return jobsById;
}

function assertPositiveDurations(jobs: readonly Job[]): void {
  for (const job of jobs) {
    if (!Number.isInteger(job.duration) || job.duration < 1) {
      throw new Error(`job ${job.id} must have a positive integer duration`);
    }
  }
}

function assertDependenciesExist(
  jobs: readonly Job[],
  jobsById: ReadonlyMap<string, Job>,
): void {
  for (const job of jobs) {
    for (const dep of job.deps ?? []) {
      if (!jobsById.has(dep)) {
        throw new Error(`unknown dependency ${dep} for job ${job.id}`);
      }
    }
  }
}

function assertNoDependencyCycle(
  jobs: readonly Job[],
  jobsById: ReadonlyMap<string, Job>,
): void {
  const done = new Set<string>();
  const onStack = new Set<string>();

  const visit = (id: string): void => {
    if (done.has(id)) return;
    if (onStack.has(id)) throw new Error(`dependency cycle at: ${id}`);

    onStack.add(id);
    for (const dep of jobsById.get(id)!.deps ?? []) visit(dep);
    onStack.delete(id);
    done.add(id);
  };

  for (const job of jobs) visit(job.id);
}

function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function byPriorityThenId(a: Job, b: Job): number {
  const priorityDifference = (b.priority ?? 0) - (a.priority ?? 0);
  return priorityDifference !== 0 ? priorityDifference : compareIds(a.id, b.id);
}

function byStartThenId(a: Run, b: Run): number {
  return a.start - b.start || compareIds(a.id, b.id);
}

function simulate(jobs: readonly Job[], limit: number): Run[] {
  const state: SimulationState = {
    started: new Set<string>(),
    finished: new Set<string>(),
    running: [],
    runs: [],
    tick: 0,
  };

  while (state.finished.size < jobs.length) {
    retireFinished(state);
    startReadyJobs(jobs, limit, state);
    state.tick = nextTick(state.running);
  }

  return state.runs.sort(byStartThenId);
}

function retireFinished(state: SimulationState): void {
  const stillRunning: Run[] = [];
  for (const run of state.running) {
    if (run.end <= state.tick) {
      state.finished.add(run.id);
    } else {
      stillRunning.push(run);
    }
  }
  state.running = stillRunning;
}

function startReadyJobs(
  jobs: readonly Job[],
  limit: number,
  state: SimulationState,
): void {
  const ready = jobs
    .filter((job) => isReady(job, state))
    .sort(byPriorityThenId);

  for (const job of ready) {
    if (state.running.length >= limit) return;
    const run = { id: job.id, start: state.tick, end: state.tick + job.duration };
    state.started.add(job.id);
    state.running.push(run);
    state.runs.push(run);
  }
}

function isReady(job: Job, state: SimulationState): boolean {
  return (
    !state.started.has(job.id) &&
    (job.deps ?? []).every((dep) => state.finished.has(dep))
  );
}

function nextTick(running: readonly Run[]): number {
  return Math.min(...running.map((run) => run.end));
}
