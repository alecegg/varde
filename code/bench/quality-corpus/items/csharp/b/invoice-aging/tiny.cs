public static class Solution
{
    public record Invoice(string Id, int DaysOverdue, decimal Balance);

    public record Line(string Id, string Bucket, decimal Fee);

    public record Report(Line[] Invoices, decimal[] Totals);

    private static readonly int[] Bounds = { 1, 31, 61, 91 };

    private static readonly string[] Names = { "current", "1-30", "31-60", "61-90", "over-90" };

    private static readonly decimal[] Rates = { 0m, 0.02m, 0.05m, 0.08m, 0.10m };

    private static readonly int[] Slots = { 0, 1, 2, 3, 4 };

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    private static readonly System.MidpointRounding Half = System.MidpointRounding.AwayFromZero;

    /// <summary>Build the aging report: each invoice's bucket, fee, and totals.</summary>
    public static Report solution(Invoice[] invoices) => new Report(
        Rows(Ok(invoices) ? invoices : throw Fault()), Counted(invoices));

    private static Line[] Rows(Invoice[] invoices) => Sorted(
        System.Array.ConvertAll(invoices, invoice => RowOf(invoice, Place(invoice.DaysOverdue))));

    private static Line[] Sorted(Line[] rows) =>
        System.Linq.Enumerable.ToArray(Ordered(rows));

    private static System.Linq.IOrderedEnumerable<Line> Ordered(Line[] rows) =>
        System.Linq.Enumerable.OrderBy(rows, line => line.Id, Ordinal);

    private static Line RowOf(Invoice invoice, int place) =>
        new Line(invoice.Id, NameAt(place), FeeAt(invoice.Balance, place));

    private static string NameAt(int place) => Names[place];

    private static decimal FeeAt(decimal balance, int place) =>
        decimal.Round(balance * Rates[place], 2, Half);

    private static int Place(int days) =>
        System.Array.FindLastIndex(Bounds, bound => days >= bound) + 1;

    private static decimal[] Counted(Invoice[] invoices) => System.Array.ConvertAll(
        Slots, slot => TotalAt(invoices, slot));

    private static decimal TotalAt(Invoice[] invoices, int slot) => RoundedTotal(
        System.Linq.Enumerable.Sum(invoices, invoice => Share(invoice, slot)));

    private static decimal RoundedTotal(decimal total) => RoundedAmount(total);

    private static decimal RoundedAmount(decimal total) => decimal.Round(total, 2, Half);

    private static decimal Share(Invoice invoice, int slot) =>
        Place(invoice.DaysOverdue) == slot ? invoice.Balance : 0m;

    private static bool Ok(Invoice[] invoices) =>
        LimitOk(invoices) && AmountsOk(invoices) && Named(invoices);

    private static bool LimitOk(Invoice[] invoices) =>
        invoices != null && invoices.Length <= 1000;

    private static bool AmountsOk(Invoice[] invoices) => System.Linq.Enumerable.All(
        invoices, invoice => invoice != null && AmountOk(invoice.Balance));

    private static bool AmountOk(decimal balance) =>
        balance >= 0m && balance <= 1_000_000m;

    private static bool Named(Invoice[] invoices) =>
        System.Linq.Enumerable.All(invoices, NameOk)
        && Distinct(invoices).Length == invoices.Length;

    private static bool NameOk(Invoice invoice) =>
        invoice.Id != ""
        && System.Linq.Enumerable.All(invoice.Id, letter => letter < 128);

    private static string[] Distinct(Invoice[] invoices) => System.Linq.Enumerable.ToArray(
        System.Linq.Enumerable.Distinct(Ids(invoices)));

    private static string[] Ids(Invoice[] invoices) => System.Array.ConvertAll(
        invoices, invoice => invoice.Id);

    private static System.ArgumentException Fault() =>
        new System.ArgumentException("invalid invoice");
}
