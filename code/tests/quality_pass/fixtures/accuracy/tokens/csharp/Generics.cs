using System;
using System.Collections.Generic;

public class Generics<T> where T : IComparable<T>
{
    private readonly List<T> items = new List<T>();

    public void Push(T item)
    {
        items.Add(item);
    }

    public IReadOnlyList<R> Map<R>(Func<T, R> mapper)
    {
        var mapped = new List<R>(items.Count);
        foreach (T item in items)
        {
            mapped.Add(mapper(item));
        }
        return mapped;
    }

    public T Maximum()
    {
        T best = items[0];
        foreach (T item in items)
        {
            if (item.CompareTo(best) > 0)
            {
                best = item;
            }
        }
        return best;
    }

    public static bool TryFirst<N>(IEnumerable<N> values, out N found)
    {
        foreach (N value in values)
        {
            found = value;
            return true;
        }
        found = default;
        return false;
    }
}
