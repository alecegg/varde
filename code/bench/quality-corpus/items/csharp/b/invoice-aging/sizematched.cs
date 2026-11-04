public static class Solution
{
    public record Invoice(string Id, int DaysOverdue, decimal Balance);

    public record Line(string Id, string Bucket, decimal Fee);

    public record Report(Line[] Invoices, decimal[] Totals);

    private static readonly int[] Bounds = { 1, 31, 61, 91 };

    private static readonly string[] Names = { "current", "1-30", "31-60", "61-90", "over-90" };

    private static readonly decimal[] Rates = { 0m, 0.02m, 0.05m, 0.08m, 0.10m };

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    private static readonly System.MidpointRounding Half = System.MidpointRounding.AwayFromZero;

    /// <summary>Build the aging report: each invoice's bucket, fee, and totals.</summary>
    public static Report solution(Invoice[] invoices)
    {
        if (invoices == null || invoices.Length > 1000)
        {
            throw new System.ArgumentException("invalid invoice");
        }
        var seen = new System.Collections.Generic.HashSet<string>();
        foreach (Invoice invoice in invoices)
        {
            if (invoice == null)
            {
                throw new System.ArgumentException("invalid invoice");
            }
            bool named = invoice.Id.Length > 0 && seen.Add(invoice.Id);
            bool ascii = System.Linq.Enumerable.All(invoice.Id, letter => letter < 128);
            if (!named || !ascii)
            {
                throw new System.ArgumentException("invalid invoice");
            }
        }
        foreach (Invoice invoice in invoices)
        {
            bool priced = invoice.Balance >= 0m && invoice.Balance <= 1_000_000m;
            if (!priced)
            {
                throw new System.ArgumentException("invalid invoice");
            }
        }
        Invoice[] ordered = System.Linq.Enumerable.ToArray(
            System.Linq.Enumerable.OrderBy(invoices, invoice => invoice.Id, Ordinal));
        var places = new int[ordered.Length];
        for (int index = 0; index < ordered.Length; index++)
        {
            int days = ordered[index].DaysOverdue;
            places[index] = System.Array.FindLastIndex(Bounds, bound => days >= bound) + 1;
        }
        var rows = new Line[ordered.Length];
        for (int index = 0; index < ordered.Length; index++)
        {
            Invoice invoice = ordered[index];
            int place = places[index];
            string bucket = Names[place];
            decimal fee = decimal.Round(invoice.Balance * Rates[place], 2, Half);
            rows[index] = new Line(invoice.Id, bucket, fee);
        }
        var totals = new decimal[Names.Length];
        for (int index = 0; index < ordered.Length; index++)
        {
            Invoice invoice = ordered[index];
            int place = places[index];
            decimal balance = invoice.Balance;
            totals[place] = totals[place] + balance;
        }
        int moneyDigits = 2;
        int totalCount = totals.Length;
        for (int place = 0; place < totalCount; place++)
        {
            decimal rawTotal = totals[place];
            decimal roundedTotal = decimal.Round(rawTotal, moneyDigits, Half);
            totals[place] = roundedTotal;
        }
        return new Report(rows, totals);
    }
}
