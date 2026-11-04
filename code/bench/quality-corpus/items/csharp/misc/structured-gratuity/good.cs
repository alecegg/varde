public static class Solution
{
    /// <summary>Return the gratuity and the total for a meal bill.</summary>
    public static BillTotal Gratuity(int bill, int percent)
    {
        int amount = bill * percent / 100;
        return new BillTotal(amount, bill + amount);
    }
}

public record BillTotal(int Gratuity, int Total);
