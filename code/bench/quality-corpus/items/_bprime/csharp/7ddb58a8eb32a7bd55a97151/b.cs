using System.Collections.Generic;
using System.Linq;

public static class Solution
{
    private const int FIRST = 0;

    public static int[] WindowSums(int[] values, int width)
    {
        return Build(Starts(values, width), values, width);
    }

    private static int[] Starts(int[] values, int width)
    {
        if (!Fits(values, width))
        {
            return new int[0];
        }
        return Enumerable.Range(FIRST, Count(values, width)).ToArray();
    }

    private static bool Fits(int[] values, int width)
    {
        return Positive(width) && LongEnough(values, width);
    }

    private static bool Positive(int width)
    {
        return width > 0;
    }

    private static bool LongEnough(int[] values, int width)
    {
        return values.Length >= width;
    }

    private static int Count(int[] values, int width)
    {
        return values.Length - width + 1;
    }

    private static int[] Build(int[] starts, int[] values, int width)
    {
        int[] sums = new int[starts.Length];
        for (int index = 0; index < starts.Length; index++)
        {
            sums[index] = Window.Total(values, starts[index], width);
        }
        return sums;
    }

    private static class Window
    {
        internal static int Total(int[] values, int start, int width)
        {
            return Slice(values, start, width).Sum();
        }

        private static IEnumerable<int> Slice(int[] values, int start, int width)
        {
            return Enumerable.Range(start, width).Select(offset => values[offset]);
        }
    }
}
