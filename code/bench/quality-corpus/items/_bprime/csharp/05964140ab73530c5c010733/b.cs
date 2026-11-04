using System;
using System.Collections.Generic;

public static class Solution
{
    private const string Separator = " | ";
    private const char Filler = ' ';

    public static string Row(string[] cells, int width)
    {
        return Join(Render(cells, width));
    }

    private static List<string> Render(string[] cells, int width)
    {
        List<string> fields = new List<string>();
        foreach (string cell in cells)
        {
            fields.Add(Pad(cell, width));
        }
        return fields;
    }

    private static string Pad(string cell, int width)
    {
        return Grow(cell, Missing(cell, width));
    }

    private static int Missing(string cell, int width)
    {
        return Math.Max(width - cell.Length, 0);
    }

    private static string Grow(string cell, int count)
    {
        return cell + new string(Filler, count);
    }

    private static string Join(List<string> cells)
    {
        return string.Join(Separator, cells);
    }
}
