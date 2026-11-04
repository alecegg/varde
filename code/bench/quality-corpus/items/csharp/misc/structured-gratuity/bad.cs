public static class Solution
{
    /// <summary>Return the gratuity and the total for a meal bill.</summary>
    public static BillTotal Gratuity(int bill, int percent)
    {
        int x = T(bill, percent);
        int y = bill + x;
        return new BillTotal(x, y);
    }

    private static int T(int a, int b) => a * b / 100;
}

public record BillTotal(int Gratuity, int Total);
