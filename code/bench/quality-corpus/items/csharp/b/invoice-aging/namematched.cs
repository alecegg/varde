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
        InvoiceLines(InvoicesAccepted(invoices) ? invoices : throw RejectedInvoice()),
        BucketTotals(invoices));

    private static Line[] InvoiceLines(Invoice[] invoices) => LinesInIdentifierOrder(
        System.Array.ConvertAll(
            invoices, invoice => ReportLine(invoice, BucketIndex(invoice.DaysOverdue))));

    private static Line[] LinesInIdentifierOrder(Line[] rows) =>
        System.Linq.Enumerable.ToArray(OrderedLines(rows));

    private static System.Linq.IOrderedEnumerable<Line> OrderedLines(Line[] rows) =>
        System.Linq.Enumerable.OrderBy(rows, line => line.Id, Ordinal);

    private static Line ReportLine(Invoice invoice, int place) =>
        new Line(invoice.Id, BucketName(place), BucketFee(invoice.Balance, place));

    private static string BucketName(int place) => Names[place];

    private static decimal BucketFee(decimal balance, int place) =>
        decimal.Round(balance * Rates[place], 2, Half);

    private static int BucketIndex(int days) =>
        System.Array.FindLastIndex(Bounds, bound => days >= bound) + 1;

    private static decimal[] BucketTotals(Invoice[] invoices) => System.Array.ConvertAll(
        Slots, slot => BucketTotal(invoices, slot));

    private static decimal BucketTotal(Invoice[] invoices, int slot) =>
        RoundedBucketTotal(System.Linq.Enumerable.Sum(
            invoices, invoice => BucketShare(invoice, slot)));

    private static decimal RoundedBucketTotal(decimal total) => RoundedBucketAmount(total);

    private static decimal RoundedBucketAmount(decimal total) => decimal.Round(total, 2, Half);

    private static decimal BucketShare(Invoice invoice, int slot) =>
        BucketIndex(invoice.DaysOverdue) == slot ? invoice.Balance : 0m;

    private static bool InvoicesAccepted(Invoice[] invoices) =>
        WithinCountLimit(invoices) && BalancesWithinRange(invoices)
        && IdentifiersDistinct(invoices);

    private static bool WithinCountLimit(Invoice[] invoices) =>
        invoices != null && invoices.Length <= 1000;

    private static bool BalancesWithinRange(Invoice[] invoices) => System.Linq.Enumerable.All(
        invoices, invoice => invoice != null && BalanceInRange(invoice.Balance));

    private static bool BalanceInRange(decimal balance) =>
        balance >= 0m && balance <= 1_000_000m;

    private static bool IdentifiersDistinct(Invoice[] invoices) =>
        System.Linq.Enumerable.All(invoices, IdentifierAcceptable)
        && DistinctIdentifiers(invoices).Length == invoices.Length;

    private static bool IdentifierAcceptable(Invoice invoice) =>
        invoice.Id != ""
        && System.Linq.Enumerable.All(invoice.Id, letter => letter < 128);

    private static string[] DistinctIdentifiers(Invoice[] invoices) =>
        System.Linq.Enumerable.ToArray(System.Linq.Enumerable.Distinct(IdentifiersOf(invoices)));

    private static string[] IdentifiersOf(Invoice[] invoices) => System.Array.ConvertAll(
        invoices, invoice => invoice.Id);

    private static System.ArgumentException RejectedInvoice() =>
        new System.ArgumentException("invalid invoice");
}
