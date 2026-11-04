using System;
using System.Collections.Generic;

public static class Solution
{
    /// <summary>Return the account balance after applying signed entries.</summary>
    public static int Balance(int opening, IEnumerable<int> entries)
    {
        List<int> values = new List<int>();
        foreach (int entry in entries)
        {
            values.Add(entry);
        }
        int acc = opening;
        for (int i = 0; i < values.Count; i++)
        {
            int e = values[i];
            if (e < 0)
            {
                acc = acc - Math.Abs(e);
            }
            else
            {
                acc = acc + e;
            }
        }
        return acc;
    }
}
