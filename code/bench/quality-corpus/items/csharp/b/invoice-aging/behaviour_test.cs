using System;
using System.Collections.Generic;
using System.Numerics;

int[] percents = { 0, 2, 5, 8, 10 };
string[] names = { "current", "1-30", "31-60", "61-90", "over-90" };
string rejected_marker = "invalid invoice";

Solution.Invoice Make(string id, int days, decimal balance) => new Solution.Invoice(id, days, balance);

int PlaceOf(int days)
{
    if (days <= 0)
    {
        return 0;
    }
    if (days <= 30)
    {
        return 1;
    }
    if (days <= 60)
    {
        return 2;
    }
    if (days <= 90)
    {
        return 3;
    }
    return 4;
}

BigInteger ScaledUnits(decimal amount)
{
    int[] bits = decimal.GetBits(amount);
    BigInteger coefficient = (uint)bits[0]
        | ((BigInteger)(uint)bits[1] << 32)
        | ((BigInteger)(uint)bits[2] << 64);
    int scale = (bits[3] >> 16) & 0x7f;
    return coefficient * BigInteger.Pow(10, 28 - scale);
}

BigInteger RoundUnits(BigInteger numerator, BigInteger denominator)
{
    BigInteger quotient = BigInteger.DivRem(numerator, denominator, out BigInteger remainder);
    if (remainder * 2 >= denominator)
    {
        quotient++;
    }
    return quotient;
}

decimal Money(BigInteger cents) => (decimal)cents / 100m;

(List<(string Id, string Bucket, decimal Fee)> Rows, decimal[] Totals) Reference(
    Solution.Invoice[] invoices)
{
    var rows = new List<(string Id, string Bucket, decimal Fee)>();
    foreach (Solution.Invoice invoice in invoices)
    {
        int place = PlaceOf(invoice.DaysOverdue);
        BigInteger balance = ScaledUnits(invoice.Balance);
        BigInteger feeCents = RoundUnits(balance * percents[place], BigInteger.Pow(10, 28));
        rows.Add((invoice.Id, names[place], Money(feeCents)));
    }
    rows.Sort((left, right) => string.CompareOrdinal(left.Id, right.Id));
    BigInteger[] scaledTotals = new BigInteger[5];
    foreach (Solution.Invoice invoice in invoices)
    {
        int place = PlaceOf(invoice.DaysOverdue);
        scaledTotals[place] += ScaledUnits(invoice.Balance);
    }
    decimal[] totals = new decimal[scaledTotals.Length];
    BigInteger unitsPerCent = BigInteger.Pow(10, 26);
    for (int place = 0; place < scaledTotals.Length; place++)
    {
        totals[place] = Money(RoundUnits(scaledTotals[place], unitsPerCent));
    }
    return (rows, totals);
}

void MatchesReference(Solution.Invoice[] invoices, string label)
{
    var (rows, totals) = Reference(invoices);
    Solution.Report report = Solution.solution(invoices);
    if (report.Invoices.Length != rows.Count)
    {
        throw new InvalidOperationException(
            $"{label}: reported {report.Invoices.Length} rows, expected {rows.Count}");
    }
    for (int index = 0; index < rows.Count; index++)
    {
        Solution.Line line = report.Invoices[index];
        var want = rows[index];
        if (line.Id != want.Id || line.Bucket != want.Bucket || line.Fee != want.Fee)
        {
            throw new InvalidOperationException(
                $"{label}[{index}]: got {line.Id}/{line.Bucket}/{line.Fee}, "
                    + $"expected {want.Id}/{want.Bucket}/{want.Fee}");
        }
    }
    if (report.Totals.Length != names.Length)
    {
        throw new InvalidOperationException($"{label}: {report.Totals.Length} totals");
    }
    for (int place = 0; place < names.Length; place++)
    {
        if (report.Totals[place] != totals[place])
        {
            throw new InvalidOperationException(
                $"{label}: {names[place]} total {report.Totals[place]}, "
                    + $"expected {totals[place]}");
        }
    }
}

void MatchesStated(
    Solution.Invoice[] invoices,
    string[] ids,
    string[] buckets,
    decimal[] fees,
    decimal[] totals,
    string label)
{
    Solution.Report report = Solution.solution(invoices);
    if (report.Invoices.Length != ids.Length)
    {
        throw new InvalidOperationException(
            $"{label}: reported {report.Invoices.Length} rows, expected {ids.Length}");
    }
    for (int index = 0; index < ids.Length; index++)
    {
        Solution.Line line = report.Invoices[index];
        if (line.Id != ids[index] || line.Bucket != buckets[index] || line.Fee != fees[index])
        {
            throw new InvalidOperationException(
                $"{label}[{index}]: got {line.Id}/{line.Bucket}/{line.Fee}, "
                    + $"expected {ids[index]}/{buckets[index]}/{fees[index]}");
        }
    }
    for (int place = 0; place < names.Length; place++)
    {
        if (report.Totals[place] != totals[place])
        {
            throw new InvalidOperationException(
                $"{label}: {names[place]} total {report.Totals[place]}, expected {totals[place]}");
        }
    }
}

var cases = new (
    Solution.Invoice[] Input,
    string[] Ids,
    string[] Buckets,
    decimal[] Fees,
    decimal[] Totals)[] {
    (
        new Solution.Invoice[0],
        new string[0],
        new string[0],
        new decimal[0],
        new[] { 0m, 0m, 0m, 0m, 0m }),
    (
        new[] { Make("A", 0, 100m) },
        new[] { "A" },
        new[] { "current" },
        new[] { 0m },
        new[] { 100m, 0m, 0m, 0m, 0m }),
    (
        new[] { Make("A", 1, 100m) },
        new[] { "A" },
        new[] { "1-30" },
        new[] { 2m },
        new[] { 0m, 100m, 0m, 0m, 0m }),
    (
        new[] { Make("A", 30, 100m) },
        new[] { "A" },
        new[] { "1-30" },
        new[] { 2m },
        new[] { 0m, 100m, 0m, 0m, 0m }),
    (
        new[] { Make("A", 31, 200m) },
        new[] { "A" },
        new[] { "31-60" },
        new[] { 10m },
        new[] { 0m, 0m, 200m, 0m, 0m }),
    (
        new[] { Make("A", 60, 50m) },
        new[] { "A" },
        new[] { "31-60" },
        new[] { 2.5m },
        new[] { 0m, 0m, 50m, 0m, 0m }),
    (
        new[] { Make("A", 61, 100m) },
        new[] { "A" },
        new[] { "61-90" },
        new[] { 8m },
        new[] { 0m, 0m, 0m, 100m, 0m }),
    (
        new[] { Make("A", 90, 50m) },
        new[] { "A" },
        new[] { "61-90" },
        new[] { 4m },
        new[] { 0m, 0m, 0m, 50m, 0m }),
    (
        new[] { Make("A", 91, 300m) },
        new[] { "A" },
        new[] { "over-90" },
        new[] { 30m },
        new[] { 0m, 0m, 0m, 0m, 300m }),
    (
        new[] { Make("B", -2, 40m) },
        new[] { "B" },
        new[] { "current" },
        new[] { 0m },
        new[] { 40m, 0m, 0m, 0m, 0m }),
    (
        new[] { Make("B", -2, 40m), Make("A", 31, 80m), Make("C", 5, 50m) },
        new[] { "A", "B", "C" },
        new[] { "31-60", "current", "1-30" },
        new[] { 4m, 0m, 1m },
        new[] { 40m, 50m, 80m, 0m, 0m }),
};

foreach (var row in cases)
{
    MatchesStated(row.Input, row.Ids, row.Buckets, row.Fees, row.Totals, "stated");
}

MatchesStated(
    new[] { Make("A", 31, 0.3m) },
    new[] { "A" },
    new[] { "31-60" },
    new[] { 0.02m },
    new[] { 0m, 0m, 0.3m, 0m, 0m },
    "half cent");
MatchesReference(
    new[]
    {
        Make("a", 31, 0.335m), Make("A", 31, 0.335m), Make("A-1", 31, 0.335m),
        Make("_", 61, 1.005m), Make("10", 91, 2.005m),
        Make("R2", 0, 3.015m), Make("R101-00001", 0, 1.005m),
    },
    "decimal ties and ordinal ids");
MatchesReference(new[] { Make("A", -1, 16.6m) }, "decimal balance");
MatchesStated(
    new[] { Make("A", 91, 1000000m) },
    new[] { "A" },
    new[] { "over-90" },
    new[] { 100000m },
    new[] { 0m, 0m, 0m, 0m, 1000000m },
    "ceiling balance");
MatchesReference(
    new[] { Make("A", int.MaxValue, 1m), Make("B", int.MinValue, 2m) },
    "extreme day counts");

var rejected = new (Solution.Invoice[] Input, string Label)[]
{
    (null, "no invoices"),
    (new Solution.Invoice[] { null }, "missing invoice"),
    (new[] { Make("", 1, 10m) }, "empty id"),
    (new[] { Make("A\u00e9", 1, 10m) }, "accented id"),
    (new[] { Make("A", 1, -1m) }, "negative balance"),
    (new[] { Make("A", 1, 1000000.01m) }, "balance past the ceiling"),
    (new[] { Make("A", 1, 10m), Make("A", 2, 20m) }, "repeated id"),
};

foreach (var row in rejected)
{
    try
    {
        Solution.solution(row.Input);
    }
    catch (ArgumentException error)
    {
        if (error.Message != rejected_marker)
        {
            throw new InvalidOperationException($"{row.Label}: reported {error.Message}");
        }
        continue;
    }
    throw new InvalidOperationException($"{row.Label}: accepted");
}

Solution.Invoice[] crowded = new Solution.Invoice[1001];
for (int index = 0; index < crowded.Length; index++)
{
    crowded[index] = Make($"C{index:D4}", index % 200, index % 1000);
}
bool crowded_rejected = false;
try
{
    Solution.solution(crowded);
}
catch (ArgumentException error)
{
    if (error.Message != rejected_marker)
    {
        throw new InvalidOperationException($"crowded: reported {error.Message}");
    }
    crowded_rejected = true;
}
if (!crowded_rejected)
{
    throw new InvalidOperationException("crowded: accepted");
}

int[] seeds = { 101, 202, 303, 404 };
foreach (int seed in seeds)
{
    Random random = new Random(seed);
    int count = 700 + (seed % 5) * 50;
    string[] identifiers = new string[count];
    for (int index = 0; index < count; index++)
    {
        identifiers[index] = $"R{seed:D3}-{index:D5}";
    }
    for (int index = count - 1; index > 0; index--)
    {
        int swap = random.Next(0, index + 1);
        string held = identifiers[index];
        identifiers[index] = identifiers[swap];
        identifiers[swap] = held;
    }
    Solution.Invoice[] invoices = new Solution.Invoice[count];
    for (int index = 0; index < count; index++)
    {
        decimal balance = random.Next(0, 1000000001) / 1000m;
        invoices[index] = Make(identifiers[index], random.Next(-30, 201), balance);
    }
    bool scrambled = false;
    for (int index = 1; index < invoices.Length; index++)
    {
        if (string.CompareOrdinal(invoices[index - 1].Id, invoices[index].Id) > 0)
        {
            scrambled = true;
        }
    }
    if (!scrambled)
    {
        throw new InvalidOperationException($"seed {seed}: identifiers arrived in order");
    }
    MatchesReference(invoices, $"seed {seed}");
}

Random large = new Random(909);
string[] big_identifiers = new string[1000];
for (int index = 0; index < big_identifiers.Length; index++)
{
    big_identifiers[index] = $"L{index:D5}";
}
for (int index = big_identifiers.Length - 1; index > 0; index--)
{
    int swap = large.Next(0, index + 1);
    string held = big_identifiers[index];
    big_identifiers[index] = big_identifiers[swap];
    big_identifiers[swap] = held;
}
Solution.Invoice[] many = new Solution.Invoice[1000];
for (int index = 0; index < many.Length; index++)
{
    many[index] = Make(big_identifiers[index], index * 37 % 260 - 30, index * 997 % 1000000001 / 1000m);
}
MatchesReference(many, "large");
