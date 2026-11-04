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
        Request order = NormalizeRequest(request);
        QuoteError? error = ValidateRequest(order);
        if (error is not null) return error;
        G.List<Checked> items = MergeItems(order.Items, out error);
        if (error is not null) return error;
        return CreateQuote(BuildLines(items), order);
    }

    private static Request NormalizeRequest(Request r) => new(
        L.Enumerable.ToArray(L.Enumerable.Select(r.Items, NormalizeItem)),
        r.Tier.Trim().ToLowerInvariant(),
        TrimAndUpper(r.Coupon), TrimAndUpper(r.Region));
    private static string TrimAndUpper(string s) => s.Trim().ToUpperInvariant();
    private static Item NormalizeItem(Item x) => new(TrimAndUpper(x.Sku), x.Qty, x.Price);
    private static QuoteError? ValidateRequest(Request r) =>
        ValidateItemCount(r.Items.Length) ?? ValidateItems(r.Items);
    private static QuoteError? ValidateItemCount(int n) => n == 0 ? new("EMPTY_ORDER", null) :
        n > 50 ? new("TOO_MANY_ITEMS", null) : null;
    private static QuoteError? ValidateItems(Item[] rows)
    {
        for (int i = 0; i < rows.Length; i++)
        {
            QuoteError? error = ValidateItem(rows[i], i);
            if (error is not null) return error;
        }
        return null;
    }
    private static QuoteError? ValidateItem(Item x, int i) =>
        ValidateSku(x, i) ?? ValidateQuantity(x, i) ?? ValidatePrice(x, i);
    private static QuoteError? ValidateSku(Item x, int i) =>
        IsValidSku(x.Sku) ? null : new("BAD_SKU", i);
    private static bool IsValidSku(string s) => SkuPattern.IsMatch(s);
    private static QuoteError? ValidateQuantity(Item x, int i) =>
        IsValidQuantity(x.Qty) ? null : new("BAD_QTY", i);
    private static bool IsValidQuantity(int q) => q is >= 1 and <= 1000;
    private static QuoteError? ValidatePrice(Item x, int i) =>
        IsValidPrice(x.Price) ? null : new("BAD_PRICE", i);
    private static bool IsValidPrice(string s) => PricePattern.IsMatch(s) && ParsePriceCents(s) > 0;
    private static long ParsePriceCents(string s)
    {
        string[] p = s.Split('.');
        string f = p.Length == 1 ? "" : p[1];
        return long.Parse(p[0]) * 100 + long.Parse((f + "00")[..2]);
    }
    private static G.List<Checked> MergeItems(Item[] rows, out QuoteError? error)
    {
        var list = new G.List<Checked>();
        error = CollectMergedItems(list, rows);
        if (error is not null) return list;
        list.Sort((a, b) => S.StringComparer.Ordinal.Compare(a.Sku, b.Sku));
        return list;
    }
    private static QuoteError? CollectMergedItems(G.List<Checked> list, Item[] rows)
    {
        for (int i = 0; i < rows.Length; i++)
        {
            QuoteError? error = MergeItemAt(list, rows[i], i);
            if (error is not null) return error;
        }
        return null;
    }
    private static QuoteError? MergeItemAt(G.List<Checked> list, Item row, int i) =>
        AddOrMergeItem(list, row, ParsePriceCents(row.Price),
        list.FindIndex(x => x.Sku == row.Sku), i);
    private static QuoteError? AddOrMergeItem(G.List<Checked> xs, Item x, long cents, int at,
        int i) =>
        at < 0 ? AddNewItem(xs, x, cents) : MergeDuplicateItem(xs, x, cents, at, i);
    private static QuoteError? AddNewItem(G.List<Checked> xs, Item x, long c)
    {
        xs.Add(new(x.Sku, x.Qty, c));
        return null;
    }
    private static QuoteError? MergeDuplicateItem(G.List<Checked> xs, Item x, long c, int at,
        int i)
    {
        Checked old = xs[at];
        return PriceConflict(old.Cents, c, i) ?? MergeQuantity(xs, old, x, at, i);
    }
    private static QuoteError? PriceConflict(long old, long current, int i) =>
        old == current ? null : new("PRICE_CONFLICT", i);
    private static QuoteError? MergeQuantity(
        G.List<Checked> xs, Checked old, Item x, int at, int i)
    {
        int qty = old.Qty + x.Qty;
        if (qty > 1000) return new("BAD_QTY", i);
        xs[at] = old with { Qty = qty };
        return null;
    }
    private static QuoteError? ValidateOptions(Request r) =>
        ValidateTier(r.Tier) ?? ValidateCoupon(r.Coupon) ?? ValidateRegion(r.Region);
    private static QuoteError? ValidateTier(string s) => IsValidTier(s) ? null : new("BAD_TIER",
        null);
    private static bool IsValidTier(string s) => s is "basic" or "silver" or "gold";
    private static QuoteError? ValidateCoupon(string s) =>
        IsValidCoupon(s) ? null : new("BAD_COUPON", null);
    private static bool IsValidCoupon(string s) => s == "" || CouponPattern.IsMatch(s);
    private static QuoteError? ValidateRegion(string s) =>
        IsValidRegion(s) ? null : new("BAD_REGION", null);
    private static bool IsValidRegion(string s) => s is "EU" or "US" or "ASIA";
    private static Line[] BuildLines(G.List<Checked> xs) =>
        L.Enumerable.ToArray(L.Enumerable.Select(xs, BuildLine));
    private static Line BuildLine(Checked x) => new(x.Sku, x.Qty, x.Cents,
        x.Cents * x.Qty);
    private static Outcome CreateQuote(Line[] lines, Request r)
    {
        QuoteError? error = ValidateOptions(r);
        if (error is not null) return error;
        return CalculateQuote(lines, r);
    }
    private static Outcome CalculateQuote(Line[] lines, Request r)
    {
        long subtotal = L.Enumerable.Sum(lines, x => x.LineCents);
        long tier = RoundHalfUp(subtotal * TierRateBasisPoints(r.Tier), 10000);
        long coupon = CalculateCouponDiscount(subtotal - tier, r.Coupon);
        return CalculateCharges(lines, r, new(subtotal, tier, coupon, subtotal - tier - coupon));
    }
    private static long TierRateBasisPoints(string s) =>
        s == "gold" ? 1000 : s == "silver" ? 500 : 0;
    private static long CalculateCouponDiscount(long net, string s) => s.StartsWith("PCT")
        ? RoundHalfUp(net * long.Parse(s[3..]), 100)
        : s.StartsWith("FIXED") ? S.Math.Min(net, long.Parse(s[5..]) * 100) : 0;
    private static long RoundHalfUp(long n, long d) => (2 * n + d) / (2 * d);
    private static Outcome CalculateCharges(Line[] lines, Request r, Adjusted a)
    {
        (long rate, long baseShip, long threshold) = RegionRates(r.Region);
        long shipping = CalculateShipping(a.Net, baseShip, threshold, r.Coupon);
        long tax = RoundHalfUp(a.Net * rate, 10000);
        return BuildQuote(lines, a, shipping, tax);
    }
    private static (long, long, long) RegionRates(string s) => s switch
    {
        "EU" => (2000, 800, 10000), "US" => (700, 500, 7500), _ => (1000, 1200, 15000)
    };
    private static long CalculateShipping(long net, long baseShip, long threshold,
        string coupon) =>
        coupon == "FREESHIP" || net >= threshold ? 0 : baseShip;
    private static Outcome BuildQuote(Line[] lines, Adjusted a, long shipping, long tax) =>
        new Quote(lines, a.Subtotal, a.Tier, a.Coupon, shipping, tax,
            a.Net + shipping + tax, BuildAppliedLabels(a, shipping, tax));
    private static string[] BuildAppliedLabels(Adjusted a, long shipping, long tax) =>
        L.Enumerable.ToArray(L.Enumerable.Concat(DiscountAdjustments(a),
        ChargeAdjustments(shipping, tax)));
    private static G.IEnumerable<string> DiscountAdjustments(Adjusted a) =>
        L.Enumerable.Concat(OptionalLabel(a.Tier > 0, "tier"), OptionalLabel(a.Coupon > 0,
        "coupon"));
    private static G.IEnumerable<string> ChargeAdjustments(long shipping, long tax) =>
        L.Enumerable.Concat(OptionalLabel(shipping == 0, "free-shipping"), OptionalLabel(tax > 0,
        "tax"));
    private static G.IEnumerable<string> OptionalLabel(bool include,
        string label) => include ? new[] { label } : S.Array.Empty<string>();
    private static readonly R.Regex SkuPattern = new(@"\A[A-Z0-9-]{3,12}\z",
        R.RegexOptions.CultureInvariant);
    private static readonly R.Regex PricePattern = new(@"\A[0-9]{1,6}(\.[0-9]{1,2})?\z",
        R.RegexOptions.CultureInvariant);
    private static readonly R.Regex CouponPattern = new(@"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|" +
        @"FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z",
        R.RegexOptions.CultureInvariant);
}
