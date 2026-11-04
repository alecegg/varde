public class Dispatcher
{
    const int Window = 60;
    readonly List<(string Name, int Limit)> channels;
    readonly Func<string, string, bool> send;
    readonly Dictionary<string, List<int>> sent = new();

    public Dispatcher(List<(string Name, int Limit)> channels, Func<string, string, bool> send)
    {
        this.channels = channels;
        this.send = send;
    }

    public string? Dispatch(string message, int now)
    {
        foreach (var (name, limit) in channels)
        {
            var recent = sent.GetValueOrDefault(name, new List<int>()).Where(t => t > now - Window).ToList();
            sent[name] = recent;
            if (recent.Count >= limit) continue;
            if (!send(name, message)) continue;
            recent.Add(now);
            return name;
        }
        return null;
    }
}
