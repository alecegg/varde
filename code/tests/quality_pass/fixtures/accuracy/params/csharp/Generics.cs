using System;
using System.Collections.Generic;

namespace Fixtures;

public static class Generics
{
    public static T Identity<T>(T value) => value;

    public static TResult Map<T, TResult>(IEnumerable<T> values, Func<T, TResult> transform) =>
        transform(default!);

    public static void Pair<TKey, TValue>(TKey key, TValue value, out TKey first)
    {
        first = key;
    }

    public static int Count<T>(IReadOnlyList<T> values, Predicate<T> match) => values.Count;

    public static bool TryPick<T>(IReadOnlyList<T> values, out T picked, bool required) =>
        required;

    public static void Consume<T>(T first, T second, T third, T fourth)
    {
    }
}
