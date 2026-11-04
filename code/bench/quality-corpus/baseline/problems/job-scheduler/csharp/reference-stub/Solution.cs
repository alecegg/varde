public record Job(string Id, int Duration, int Priority, string[] Deps);

public record Run(string Id, int Start, int End);

public static class Scheduler
{
    public static List<Run> RunJobs(List<Job> jobs, int limit)
    {
        if (limit < 1) throw new ArgumentException("limit must be at least 1");
        var byId = jobs.ToDictionary(j => j.Id);
        if (jobs.Any(j => j.Deps.Any(d => !byId.ContainsKey(d)))) throw new ArgumentException("unknown dependency");
        var pending = new HashSet<string>(byId.Keys);
        var done = new HashSet<string>();
        var running = new List<Run>();
        var runs = new List<Run>();
        int now = 0;
        while (pending.Count > 0 || running.Count > 0)
        {
            foreach (var run in running.Where(r => r.End <= now)) done.Add(run.Id);
            running.RemoveAll(r => r.End <= now);
            var ready = pending.Select(id => byId[id])
                .Where(j => j.Deps.All(done.Contains))
                .OrderByDescending(j => j.Priority).ThenBy(j => j.Id, StringComparer.Ordinal)
                .Take(limit - running.Count).ToList();
            foreach (var job in ready)
            {
                var run = new Run(job.Id, now, now + job.Duration);
                running.Add(run);
                runs.Add(run);
                pending.Remove(job.Id);
            }
            if (running.Count == 0 && pending.Count > 0) throw new InvalidOperationException("dependency cycle");
            if (running.Count > 0) now = running.Min(r => r.End);
        }
        return runs.OrderBy(r => r.Start).ThenBy(r => r.Id, StringComparer.Ordinal).ToList();
    }
}
