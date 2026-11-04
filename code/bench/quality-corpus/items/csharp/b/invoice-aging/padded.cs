public static class Solution
{
    public record Invoice(string Id, int DaysOverdue, decimal Balance);

    public record Line(string Id, string Bucket, decimal Fee);

    public record Report(Line[] Invoices, decimal[] Totals);

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    private static readonly System.MidpointRounding Half = System.MidpointRounding.AwayFromZero;

    /// <summary>Build the aging report: each invoice's bucket, fee, and totals.</summary>
    public static Report solution(Invoice[] invoices) => new Report(
        LinesOf(RulesHold(invoices) ? invoices : throw RejectedInvoice()),
        BucketTotals(invoices));

    private static Line[] LinesOf(Invoice[] invoices)
    {
        Line[] built = System.Array.ConvertAll(
            invoices, invoice => LineFor(invoice, BucketIndexOf(invoice.DaysOverdue)));
        return SortByLabel(built);
    }

    private static Line[] SortByLabel(Line[] rows)
    {
        System.Linq.IOrderedEnumerable<Line> sequence = OrderedRows(rows);
        Line[] sorted = System.Linq.Enumerable.ToArray(sequence);
        return sorted;
    }

    private static System.Linq.IOrderedEnumerable<Line> OrderedRows(Line[] rows)
    {
        System.Linq.IOrderedEnumerable<Line> sequence =
            System.Linq.Enumerable.OrderBy(rows, line => line.Id, Ordinal);
        return sequence;
    }

    private static Line LineFor(Invoice invoice, int place)
    {
        string label = BucketNameAt(place);
        decimal fee = BucketFeeFor(invoice.Balance, place);
        return new Line(invoice.Id, label, fee);
    }

    private static string BucketNameAt(int place)
    {
        string label = place switch
        {
            0 => "current",
            1 => "1-30",
            2 => "31-60",
            3 => "61-90",
            _ => "over-90",
        };
        return label;
    }

    private static decimal BucketFeeFor(decimal balance, int place)
    {
        decimal rate = place switch
        {
            0 => 0m,
            1 => 0.02m,
            2 => 0.05m,
            3 => 0.08m,
            _ => 0.10m,
        };
        decimal exact = balance * rate;
        decimal fee = decimal.Round(exact, 2, Half);
        return fee;
    }

    private static int BucketIndexOf(int days)
    {
        int place;
        if (days <= 0)
        {
            place = 0;
        }
        else if (days <= 30)
        {
            place = 1;
        }
        else if (days <= 60)
        {
            place = 2;
        }
        else if (days <= 90)
        {
            place = 3;
        }
        else
        {
            place = 4;
        }
        return place;
    }

    private static decimal[] BucketTotals(Invoice[] invoices)
    {
        int slotCount = 5;
        decimal[] totals = new decimal[slotCount];
        for (int slot = 0; slot < slotCount; slot++)
        {
            decimal roundedTotal = BucketTotalFor(invoices, slot);
            totals[slot] = roundedTotal;
        }
        return totals;
    }

    private static decimal BucketTotalFor(Invoice[] invoices, int slot) =>
        ReportedTotal(System.Linq.Enumerable.Sum(
            System.Array.ConvertAll(invoices, invoice => AmountInSlot(invoice, slot))));

    private static decimal ReportedTotal(decimal total)
    {
        decimal integerPart = decimal.Truncate(total);
        decimal fractionalPart = total - integerPart;
        int precision = fractionalPart == 0m ? 0 : 2;
        return RoundValue(total, precision);
    }

    private static decimal RoundValue(decimal total, int precision)
    {
        decimal scale = precision == 0 ? 1m : 100m;
        decimal scaledTotal = total * scale;
        decimal roundedTotal = decimal.Round(scaledTotal, 0, Half);
        return roundedTotal / scale;
    }

    private static decimal AmountInSlot(Invoice invoice, int slot)
    {
        int place = BucketIndexOf(invoice.DaysOverdue);
        if (place == slot)
        {
            return invoice.Balance;
        }
        return 0m;
    }

    private static bool RulesHold(Invoice[] invoices)
    {
        bool withinLimit = WithinInvoiceLimit(invoices);
        if (!withinLimit)
        {
            return false;
        }
        bool amountsValid = BalancesWithinRange(invoices);
        if (!amountsValid)
        {
            return false;
        }
        return NamedInvoices(invoices);
    }

    private static bool WithinInvoiceLimit(Invoice[] invoices)
    {
        if (invoices == null)
        {
            return false;
        }
        int supplied = invoices.Length;
        int maximum = 1000;
        return supplied <= maximum;
    }

    private static bool BalancesWithinRange(Invoice[] invoices) => System.Linq.Enumerable.All(
        invoices, invoice => invoice != null && BalanceInRange(invoice.Balance));

    private static bool BalanceInRange(decimal balance)
    {
        decimal lowest = 0m;
        decimal highest = 1_000_000m;
        bool inside = balance >= lowest && balance <= highest;
        return inside;
    }

    private static bool NamedInvoices(Invoice[] invoices)
    {
        bool everyName = System.Linq.Enumerable.All(invoices, IdentifierAcceptable);
        string[] distinct = DistinctIdentifiers(invoices);
        int supplied = invoices.Length;
        return everyName && distinct.Length == supplied;
    }

    private static bool IdentifierAcceptable(Invoice invoice)
    {
        string identifier = invoice.Id;
        bool hasText = identifier.Length > 0;
        bool asciiOnly = System.Linq.Enumerable.All(identifier, letter => letter < 128);
        return hasText && asciiOnly;
    }

    private static string[] DistinctIdentifiers(Invoice[] invoices)
    {
        string[] identifiers = IdentifiersOf(invoices);
        var seen = new System.Collections.Generic.HashSet<string>();
        foreach (string identifier in identifiers)
        {
            seen.Add(identifier);
        }
        return System.Linq.Enumerable.ToArray(seen);
    }

    private static string[] IdentifiersOf(Invoice[] invoices)
    {
        int count = invoices.Length;
        string[] identifiers = new string[count];
        for (int index = 0; index < count; index++)
        {
            identifiers[index] = invoices[index].Id;
        }
        return identifiers;
    }

    private static System.ArgumentException RejectedInvoice()
    {
        const string reason = "invalid invoice";
        System.ArgumentException failure = new System.ArgumentException(reason);
        return failure;
    }
}
