using System;

public readonly record struct Point(int X, int Y)
{
    public static readonly Point Origin = new Point(0, 0);

    public Point Shift(int delta) => new Point(X + delta, Y + delta);

    public int Manhattan => Math.Abs(X) + Math.Abs(Y);
}

public static class Texts
{
    public const string Header = """
        name,value
        alpha,1
        """;

    public static string Describe(Point point)
    {
        string path = @"C:\fixtures\points";
        return $"point at {path}: ({point.X},{point.Y})";
    }
}
