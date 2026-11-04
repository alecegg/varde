using System;
using System.Collections.Generic;

public sealed class Basics
{
    private const int MaxRetries = 3;
    private const string DefaultName = "anonymous";
    private readonly List<string> names;

    public Basics(List<string> names)
    {
        this.names = names;
    }

    public int Count()
    {
        int total = 0;
        foreach (string name in names)
        {
            if (!string.IsNullOrEmpty(name))
            {
                total++;
            }
        }
        return total;
    }

    public string Render(int index)
    {
        if (index < 0 || index >= names.Count)
        {
            throw new ArgumentOutOfRangeException(nameof(index));
        }
        return names[index].ToUpperInvariant();
    }
}
