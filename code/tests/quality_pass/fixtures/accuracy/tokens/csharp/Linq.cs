using System;
using System.Collections.Generic;
using System.Linq;

public static class Queries
{
    public static List<string> Top(IEnumerable<string> names, int limit)
    {
        return names
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .OrderBy(name => name.Length)
            .ThenBy(name => name, StringComparer.Ordinal)
            .Take(limit)
            .ToList();
    }

    public static int TotalLength(IEnumerable<string> names)
    {
        return names.Sum(name => name?.Length ?? 0);
    }

    public static Dictionary<char, int> Histogram(string text)
    {
        var counts = new Dictionary<char, int>();
        foreach (char symbol in text)
        {
            counts.TryGetValue(symbol, out int current);
            counts[symbol] = current + 1;
        }
        return counts;
    }
}
