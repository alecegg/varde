using static Harness;

static Job J(string id, int duration, int priority = 0, params string[] deps) => new(id, duration, priority, deps);

static string Plan(List<Job> jobs, int limit) =>
    string.Join(" ", Scheduler.RunJobs(jobs, limit).Select(r => $"{r.Id}:{r.Start}-{r.End}"));

Case("single job", () => Equal("a:0-3", Plan(new() { J("a", 3) }, 1)));

Case("dependency order", () =>
    Equal("a:0-2 b:2-5", Plan(new() { J("b", 3, 0, "a"), J("a", 2) }, 2)));

Case("priority among ready jobs", () =>
    Equal("b:0-1 c:1-2 a:2-3", Plan(new() { J("a", 1, 1), J("b", 1, 5), J("c", 1, 3) }, 1)));

Case("limit one runs serially", () =>
    Equal("a:0-2 b:2-4 c:4-6", Plan(new() { J("c", 2), J("a", 2), J("b", 2) }, 1)));

Case("limit two runs in parallel", () =>
    Equal("a:0-2 b:0-2 c:2-4", Plan(new() { J("a", 2), J("b", 2), J("c", 2) }, 2)));

Case("equal priority breaks by id", () =>
    Equal("a:0-1 x:1-2", Plan(new() { J("x", 1), J("a", 1) }, 1)));

Case("cycle is an error", () =>
{
    Throws(() => Scheduler.RunJobs(new() { J("a", 1, 0, "b"), J("b", 1, 0, "a") }, 2));
    Throws(() => Scheduler.RunJobs(new() { J("a", 1, 0, "a") }, 2));
});

Case("invalid input is an error", () =>
{
    Throws(() => Scheduler.RunJobs(new() { J("a", 1, 0, "missing") }, 1));
    Throws(() => Scheduler.RunJobs(new() { J("a", 1) }, 0));
});

return Finish();
