using G = System.Collections.Generic;
using L = System.Linq;
using R = System.Text.RegularExpressions;
using S = System;


public static class Solution
{
    public abstract record Outcome;
    public sealed record Item(string Sku, int Qty, string Price);
    public sealed record Request(Item[] Items, string Tier, string Coupon, string Region);
    public sealed record Line(string Sku, int Qty, long UnitCents, long LineCents);
    public sealed record Quote(Line[] Lines, long Subtotal, long TierDiscount,
        long CouponDiscount,
        long Shipping, long Tax, long Total, string[] Applied) : Outcome;
    public sealed record QuoteError(string Error, int? Index) : Outcome;

    private sealed record Checked(string Sku, int Qty, long Cents);
    private sealed record Adjusted(long Subtotal, long Tier, long Coupon, long Net);

    /// <summary>
    /// Quote normalized order lines with discounts, shipping, tax, and applied adjustments.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Request order = Norm(request);
        QuoteError? error = Check(order);
        if (error is not null) return error;
        G.List<Checked> items = Merge(order.Items, out error);
        if (error is not null) return error;
        return QuoteIt(Prices(items), order);
    }

    private static Request Norm(Request r) => new(
        L.Enumerable.ToArray(L.Enumerable.Select(r.Items, NormItem)),
        r.Tier.Trim().ToLowerInvariant(),
        Up(r.Coupon), Up(r.Region));
    private static string Up(string s) => s.Trim().ToUpperInvariant();
    private static Item NormItem(Item x) => new(Up(x.Sku), x.Qty, x.Price);
    private static QuoteError? Check(Request r) => Limit(r.Items.Length) ?? Rows(r.Items);
    private static QuoteError? Limit(int n) => n == 0 ? new("EMPTY_ORDER", null) :
        n > 50 ? new("TOO_MANY_ITEMS", null) : null;
    private static QuoteError? Rows(Item[] rows)
    {
        for (int i = 0; i < rows.Length; i++)
        {
            QuoteError? error = Row(rows[i], i);
            if (error is not null) return error;
        }
        return null;
    }
    private static QuoteError? Row(Item x, int i) =>
        SkuError(x, i) ?? QtyError(x, i) ?? PriceError(x, i);
    private static QuoteError? SkuError(Item x, int i) =>
        SkuOk(x.Sku) ? null : new("BAD_SKU", i);
    private static bool SkuOk(string s) => SkuPattern.IsMatch(s);
    private static QuoteError? QtyError(Item x, int i) =>
        QtyOk(x.Qty) ? null : new("BAD_QTY", i);
    private static bool QtyOk(int q) => q is >= 1 and <= 1000;
    private static QuoteError? PriceError(Item x, int i) =>
        PriceOk(x.Price) ? null : new("BAD_PRICE", i);
    private static bool PriceOk(string s) => PricePattern.IsMatch(s) && Cents(s) > 0;
    private static long Cents(string s)
    {
        string[] p = s.Split('.');
        string f = p.Length == 1 ? "" : p[1];
        return long.Parse(p[0]) * 100 + long.Parse((f + "00")[..2]);
    }
    private static G.List<Checked> Merge(Item[] rows, out QuoteError? error)
    {
        var list = new G.List<Checked>();
        error = Collect(list, rows);
        if (error is not null) return list;
        list.Sort((a, b) => S.StringComparer.Ordinal.Compare(a.Sku, b.Sku));
        return list;
    }
    private static QuoteError? Collect(G.List<Checked> list, Item[] rows)
    {
        for (int i = 0; i < rows.Length; i++)
        {
            QuoteError? error = MergeRow(list, rows[i], i);
            if (error is not null) return error;
        }
        return null;
    }
    private static QuoteError? MergeRow(G.List<Checked> list, Item row, int i) =>
        Add(list, row, Cents(row.Price), list.FindIndex(x => x.Sku == row.Sku), i);
    private static QuoteError? Add(G.List<Checked> xs, Item x, long cents, int at, int i) =>
        at < 0 ? Put(xs, x, cents) : Combine(xs, x, cents, at, i);
    private static QuoteError? Put(G.List<Checked> xs, Item x, long c)
    {
        xs.Add(new(x.Sku, x.Qty, c));
        return null;
    }
    private static QuoteError? Combine(G.List<Checked> xs, Item x, long c, int at, int i)
    {
        Checked old = xs[at];
        return Conflict(old.Cents, c, i) ?? MergeQty(xs, old, x, at, i);
    }
    private static QuoteError? Conflict(long old, long current, int i) =>
        old == current ? null : new("PRICE_CONFLICT", i);
    private static QuoteError? MergeQty(
        G.List<Checked> xs, Checked old, Item x, int at, int i)
    {
        int qty = old.Qty + x.Qty;
        if (qty > 1000) return new("BAD_QTY", i);
        xs[at] = old with { Qty = qty };
        return null;
    }
    private static QuoteError? Options(Request r) =>
        TierError(r.Tier) ?? CouponError(r.Coupon) ?? RegionError(r.Region);
    private static QuoteError? TierError(string s) => TierOk(s) ? null : new("BAD_TIER", null);
    private static bool TierOk(string s) => s is "basic" or "silver" or "gold";
    private static QuoteError? CouponError(string s) =>
        CouponOk(s) ? null : new("BAD_COUPON", null);
    private static bool CouponOk(string s) => s == "" || CouponPattern.IsMatch(s);
    private static QuoteError? RegionError(string s) =>
        RegionOk(s) ? null : new("BAD_REGION", null);
    private static bool RegionOk(string s) => s is "EU" or "US" or "ASIA";
    private static Line[] Prices(G.List<Checked> xs) =>
        L.Enumerable.ToArray(L.Enumerable.Select(xs, LineFor));
    private static Line LineFor(Checked x) => new(x.Sku, x.Qty, x.Cents, x.Cents * x.Qty);
    private static Outcome QuoteIt(Line[] lines, Request r)
    {
        QuoteError? error = Options(r);
        if (error is not null) return error;
        return PriceQuote(lines, r);
    }
    private static Outcome PriceQuote(Line[] lines, Request r)
    {
        long subtotal = L.Enumerable.Sum(lines, x => x.LineCents);
        long tier = Round(subtotal * TierRate(r.Tier), 10000);
        long coupon = CouponDiscount(subtotal - tier, r.Coupon);
        return Finish(lines, r, new(subtotal, tier, coupon, subtotal - tier - coupon));
    }
    private static long TierRate(string s) => s == "gold" ? 1000 : s == "silver" ? 500 : 0;
    private static long CouponDiscount(long net, string s) => s.StartsWith("PCT")
        ? Round(net * long.Parse(s[3..]), 100)
        : s.StartsWith("FIXED") ? S.Math.Min(net, long.Parse(s[5..]) * 100) : 0;
    private static long Round(long n, long d) => (2 * n + d) / (2 * d);
    private static Outcome Finish(Line[] lines, Request r, Adjusted a)
    {
        (long rate, long baseShip, long threshold) = Region(r.Region);
        long shipping = Ship(a.Net, baseShip, threshold, r.Coupon);
        long tax = Round(a.Net * rate, 10000);
        return Build(lines, a, shipping, tax);
    }
    private static (long, long, long) Region(string s) => s switch
    {
        "EU" => (2000, 800, 10000), "US" => (700, 500, 7500), _ => (1000, 1200, 15000)
    };
    private static long Ship(long net, long baseShip, long threshold, string coupon) =>
        coupon == "FREESHIP" || net >= threshold ? 0 : baseShip;
    private static Outcome Build(Line[] lines, Adjusted a, long shipping, long tax) =>
        new Quote(lines, a.Subtotal, a.Tier, a.Coupon, shipping, tax,
            a.Net + shipping + tax, Applied(a, shipping, tax));
    private static string[] Applied(Adjusted a, long shipping, long tax) =>
        L.Enumerable.ToArray(L.Enumerable.Concat(DiscountLabels(a), ChargeLabels(shipping, tax)));
    private static G.IEnumerable<string> DiscountLabels(Adjusted a) =>
        L.Enumerable.Concat(Labels(a.Tier > 0, "tier"), Labels(a.Coupon > 0, "coupon"));
    private static G.IEnumerable<string> ChargeLabels(long shipping, long tax) =>
        L.Enumerable.Concat(Labels(shipping == 0, "free-shipping"), Labels(tax > 0, "tax"));
    private static G.IEnumerable<string> Labels(bool include,
        string label) => include ? new[] { label } : S.Array.Empty<string>();
    private static readonly R.Regex SkuPattern = new(@"\A[A-Z0-9-]{3,12}\z",
        R.RegexOptions.CultureInvariant);
    private static readonly R.Regex PricePattern = new(@"\A[0-9]{1,6}(\.[0-9]{1,2})?\z",
        R.RegexOptions.CultureInvariant);
    private static readonly R.Regex CouponPattern = new(@"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|" +
        @"FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z",
        R.RegexOptions.CultureInvariant);
}
