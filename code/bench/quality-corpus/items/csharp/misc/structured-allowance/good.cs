using System.Linq;

public static class Solution
{
    /// <summary>Return the amount left after the recorded expenses.</summary>
    public static int Remaining(int start, int[] expenses) => start - expenses.Sum();
}
