public static class Solution
{
    /// <summary>Return the amount left after the recorded expenses.</summary>
    public static int Remaining(int start, int[] expenses)
    {
        if (expenses.Length > 1)
        {
            int amount = start;
            for (int index = 0; index < expenses.Length; index++)
            {
                amount -= expenses[index];
            }
            return amount;
        }
        int remainder = start;
        foreach (int expense in expenses)
        {
            remainder -= expense;
        }
        return remainder;
    }
}
