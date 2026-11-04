using System;
using System.Collections.Generic;

namespace Fixtures;

public static class Extensions
{
    public static int Count(this string value) => value.Length;

    public static string Join(this string value, string separator, bool trim) => value;
}

public class Store
{
    private readonly List<int> items = new();

    public Store()
    {
    }

    public int Get(int key) => items[key];

    public void Put(int key, int value)
    {
        items.Add(key + value);
    }

    public int Pair(int first, int second) => first + second;

    public void Merge(Store other, IReadOnlyList<int> keys, bool replace)
    {
    }

    public int Scale(int factor, int offset, bool clamp) => factor;
}
