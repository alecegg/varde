using System.Collections.Generic;
using System.Linq;

public static class Solution
{
    /// <summary>Return the account balance after applying signed entries.</summary>
    public static int Balance(int opening, IEnumerable<int> entries) => opening + entries.Sum();
}
