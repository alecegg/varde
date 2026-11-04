public static class Harness
{
    static readonly List<string> Failures = new();
    static int count;

    public static void Case(string name, Action body)
    {
        count++;
        try { body(); Console.WriteLine($"ok {name}"); }
        catch (Exception e) { Failures.Add(name); Console.WriteLine($"FAIL {name}: {e.Message}"); }
    }

    public static void Equal<T>(T expected, T actual)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new Exception($"expected {expected} but got {actual}");
    }

    public static void Throws(Action body)
    {
        try { body(); } catch { return; }
        throw new Exception("expected an exception");
    }

    public static int Finish()
    {
        Console.WriteLine($"{count - Failures.Count}/{count} passed");
        return Failures.Count == 0 ? 0 : 1;
    }
}
