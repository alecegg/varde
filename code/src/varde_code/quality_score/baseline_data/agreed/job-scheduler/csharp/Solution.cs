using System;
using System.Collections.Generic;
using System.Linq;

public record Job(string Id, int Duration, int Priority, string[] Deps);

public record Run(string Id, int Start, int End);

public static class Scheduler
{
    public static List<Run> RunJobs(List<Job> jobs, int limit)
    {
        ValidateLimit(limit);
        var jobsById = IndexAndValidateJobs(jobs);
        var dependencies = BuildDependencies(jobs, jobsById);

        return new Simulation(jobs, limit, jobsById, dependencies).Execute();
    }

    private static void ValidateLimit(int limit)
    {
        if (limit < 1)
            throw new ArgumentException("limit must be at least 1", nameof(limit));
    }

    private static Dictionary<string, Job> IndexAndValidateJobs(List<Job> jobs)
    {
        var jobsById = new Dictionary<string, Job>();

        foreach (var job in jobs)
        {
            if (job.Deps is null)
                throw new ArgumentException($"Dependencies for job '{job.Id}' cannot be null.");

            if (job.Duration < 1)
                throw new ArgumentException($"Job '{job.Id}' must have a positive duration.");

            if (!jobsById.TryAdd(job.Id, job))
                throw new ArgumentException($"Duplicate job id '{job.Id}'.");
        }

        return jobsById;
    }

    private static DependencyGraph BuildDependencies(
        List<Job> jobs,
        Dictionary<string, Job> jobsById)
    {
        var remainingDependencies = new Dictionary<string, int>();
        var dependents = new Dictionary<string, List<string>>();

        foreach (var job in jobs)
        {
            var uniqueDependencies = job.Deps.Distinct(StringComparer.Ordinal).ToList();

            foreach (var dependencyId in uniqueDependencies)
            {
                if (!jobsById.ContainsKey(dependencyId))
                    throw new ArgumentException(
                        $"Unknown dependency '{dependencyId}' of job '{job.Id}'.");

                if (!dependents.TryGetValue(dependencyId, out var dependentJobs))
                {
                    dependentJobs = new List<string>();
                    dependents[dependencyId] = dependentJobs;
                }

                dependentJobs.Add(job.Id);
            }

            remainingDependencies[job.Id] = uniqueDependencies.Count;
        }

        return new DependencyGraph(remainingDependencies, dependents);
    }

    private sealed record DependencyGraph(
        Dictionary<string, int> RemainingDependencies,
        Dictionary<string, List<string>> Dependents);

    private sealed class Simulation
    {
        private readonly int _limit;
        private readonly int _jobCount;
        private readonly Dictionary<string, Job> _jobsById;
        private readonly Dictionary<string, int> _remainingDependencies;
        private readonly Dictionary<string, List<string>> _dependents;
        private readonly SortedSet<Job> _readyJobs = new(JobPriorityComparer.Instance);
        private readonly PriorityQueue<Run, int> _runningJobs = new();
        private readonly List<Run> _runs = new();
        private int _finishedCount;
        private int _time;

        public Simulation(
            List<Job> jobs,
            int limit,
            Dictionary<string, Job> jobsById,
            DependencyGraph dependencies)
        {
            _limit = limit;
            _jobCount = jobs.Count;
            _jobsById = jobsById;
            _remainingDependencies = dependencies.RemainingDependencies;
            _dependents = dependencies.Dependents;

            foreach (var job in jobs)
                if (_remainingDependencies[job.Id] == 0)
                    _readyJobs.Add(job);
        }

        public List<Run> Execute()
        {
            while (_finishedCount < _jobCount)
            {
                ReleaseFinishedJobs();
                StartReadyJobs();

                if (_finishedCount == _jobCount)
                    break;

                if (_runningJobs.Count == 0)
                    throw new InvalidOperationException("dependency cycle detected");

                _time = _runningJobs.Peek().End;
            }

            return _runs
                .OrderBy(run => run.Start)
                .ThenBy(run => run.Id, StringComparer.Ordinal)
                .ToList();
        }

        private void ReleaseFinishedJobs()
        {
            while (_runningJobs.TryPeek(out _, out var endTime) && endTime <= _time)
            {
                var finishedRun = _runningJobs.Dequeue();
                _finishedCount++;

                if (!_dependents.TryGetValue(finishedRun.Id, out var dependentIds))
                    continue;

                foreach (var dependentId in dependentIds)
                {
                    _remainingDependencies[dependentId]--;

                    if (_remainingDependencies[dependentId] == 0)
                        _readyJobs.Add(_jobsById[dependentId]);
                }
            }
        }

        private void StartReadyJobs()
        {
            while (_runningJobs.Count < _limit && _readyJobs.Count > 0)
            {
                var job = _readyJobs.Min!;
                _readyJobs.Remove(job);

                var endTime = checked(_time + job.Duration);
                var run = new Run(job.Id, _time, endTime);
                _runs.Add(run);
                _runningJobs.Enqueue(run, endTime);
            }
        }
    }

    private sealed class JobPriorityComparer : IComparer<Job>
    {
        public static JobPriorityComparer Instance { get; } = new();

        public int Compare(Job? left, Job? right)
        {
            if (ReferenceEquals(left, right))
                return 0;
            if (left is null)
                return -1;
            if (right is null)
                return 1;

            var priorityOrder = right.Priority.CompareTo(left.Priority);
            return priorityOrder != 0
                ? priorityOrder
                : StringComparer.Ordinal.Compare(left.Id, right.Id);
        }
    }
}
