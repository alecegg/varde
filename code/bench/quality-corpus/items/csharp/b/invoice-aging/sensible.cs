public static class Solution
{
    public record Invoice(string Id, int DaysOverdue, decimal Balance);

    public record Line(string Id, string Bucket, decimal Fee);

    public record Report(Line[] Invoices, decimal[] Totals);

    private const decimal BalanceLimit = 1_000_000m;

    private static readonly int[] Bounds = { 1, 31, 61, 91 };

    private static readonly string[] Names = { "current", "1-30", "31-60", "61-90", "over-90" };

    private static readonly decimal[] Rates = { 0m, 0.02m, 0.05m, 0.08m, 0.10m };

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    private static readonly System.MidpointRounding Half = System.MidpointRounding.AwayFromZero;

    /// <summary>Build the aging report: each invoice's bucket, fee, and totals.</summary>
    public static Report solution(Invoice[] invoices)
    {
        if (!LimitsOk(invoices) || !IdsOk(invoices))
        {
            throw new System.ArgumentException("invalid invoice");
        }
        int[] places = Places(invoices);
        return new Report(LineRows(invoices, places), BucketTotals(invoices, places));
    }

    private static bool LimitsOk(Invoice[] invoices)
    {
        if (invoices == null || invoices.Length > 1000)
        {
            return false;
        }
        foreach (Invoice invoice in invoices)
        {
            if (invoice == null)
            {
                return false;
            }
            if (invoice.Balance < 0m || invoice.Balance > BalanceLimit)
            {
                return false;
            }
        }
        return true;
    }

    private static bool IdsOk(Invoice[] invoices)
    {
        var seen = new System.Collections.Generic.HashSet<string>();
        foreach (Invoice invoice in invoices)
        {
            if (invoice.Id.Length == 0 || !seen.Add(invoice.Id))
            {
                return false;
            }
            if (!System.Linq.Enumerable.All(invoice.Id, letter => letter < 128))
            {
                return false;
            }
        }
        return true;
    }

    private static int[] Places(Invoice[] invoices)
    {
        var places = new int[invoices.Length];
        for (int index = 0; index < invoices.Length; index++)
        {
            Invoice invoice = invoices[index];
            places[index] = System.Array.FindLastIndex(
                Bounds, bound => invoice.DaysOverdue >= bound) + 1;
        }
        return places;
    }

    private static Line[] LineRows(Invoice[] invoices, int[] places)
    {
        return System.Linq.Enumerable.ToArray(
            System.Linq.Enumerable.OrderBy(
                System.Linq.Enumerable.Zip(
                    invoices,
                    places,
                    (invoice, place) => new Line(
                        invoice.Id,
                        Names[place],
                        decimal.Round(invoice.Balance * Rates[place], 2, Half))),
                line => line.Id,
                Ordinal));
    }

    private static decimal[] BucketTotals(Invoice[] invoices, int[] places)
    {
        var totals = new decimal[Names.Length];
        for (int index = 0; index < invoices.Length; index++)
        {
            totals[places[index]] = totals[places[index]] + invoices[index].Balance;
        }
        return System.Array.ConvertAll(
            totals, total => decimal.Round(total, 2, Half));
    }
}
