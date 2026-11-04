using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;

public static class Solution
{
    public abstract record Outcome;
    public sealed record Item(string Sku, int Qty, string Price);
    public sealed record Request(Item[] Items, string Tier, string Coupon, string Region);
    public sealed record Line(string Sku, int Qty, long UnitCents, long LineCents);
    public sealed record Quote(Line[] Lines, long Subtotal, long TierDiscount, long CouponDiscount,
        long Shipping, long Tax, long Total, string[] Applied) : Outcome;
    public sealed record QuoteError(string Error, int? Index) : Outcome;

    private sealed record PricedItem(Item Item, long UnitCents);
    private sealed record Pricing(Line[] Lines, long Subtotal, long TierDiscount,
        long CouponDiscount, long Net, long Shipping, long Tax);
    private sealed record MergeResult(
        Dictionary<string, (int Quantity, long UnitCents)> Merged, Outcome? Error);

    private static readonly System.Text.RegularExpressions.Regex SkuPattern =
        new(@"\A[A-Z0-9-]{3,12}\z");
    private static readonly Regex PricePattern = new(@"\A[0-9]{1,6}(\.[0-9]{1,2})?\z");
    private static readonly Regex CouponPattern = new(
        @"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z");

    /// <summary>
    /// Quote normalized order lines with discounts, shipping, tax, and applied adjustments.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Request normalized = Normalize(request);
        Outcome? failure = Validate(normalized, out List<PricedItem> items);
        if (failure is not null) return failure;
        MergeResult merge = Merge(items);
        if (merge.Error is not null) return merge.Error;
        failure = ValidateOptions(normalized);
        if (failure is not null) return failure;
        Pricing pricing = ApplyTier(BuildPricing(merge.Merged), normalized.Tier);
        pricing = ApplyCoupon(pricing, normalized.Coupon);
        pricing = ApplyShipping(pricing, normalized.Region, normalized.Coupon);
        pricing = ApplyTax(pricing, normalized.Region);
        return Finish(pricing);
    }

    private static Request Normalize(Request request)
    {
        var rows = new Item[request.Items.Length];
        for (int index = 0; index < request.Items.Length; index++)
        {
            Item row = request.Items[index];
            rows[index] = new Item(row.Sku.Trim().ToUpperInvariant(), row.Qty, row.Price);
        }
        return new Request(rows, request.Tier.Trim().ToLowerInvariant(),
            request.Coupon.Trim().ToUpperInvariant(), request.Region.Trim().ToUpperInvariant());
    }

    private static Outcome? Validate(Request request, out List<PricedItem> items)
    {
        items = new List<PricedItem>();
        Outcome? shape = ValidateCount(request.Items.Length);
        if (shape is not null) return shape;
        for (int index = 0; index < request.Items.Length; index++)
        {
            Outcome? error = ValidateRow(request.Items[index], index, out long cents);
            if (error is not null) return error;
            items.Add(new PricedItem(request.Items[index], cents));
        }
        return null;
    }

    private static Outcome? ValidateCount(int count)
    {
        if (count == 0) return new QuoteError("EMPTY_ORDER", null);
        if (count > 50) return new QuoteError("TOO_MANY_ITEMS", null);
        return null;
    }

    private static Outcome? ValidateRow(Item row, int index, out long cents)
    {
        cents = 0;
        if (!SkuPattern.IsMatch(row.Sku)) return new QuoteError("BAD_SKU", index);
        if (row.Qty is < 1 or > 1000) return new QuoteError("BAD_QTY", index);
        if (!PricePattern.IsMatch(row.Price)) return new QuoteError("BAD_PRICE", index);
        cents = ParseCents(row.Price);
        if (cents > 0) return null;
        return new QuoteError("BAD_PRICE", index);
    }

    private static long ParseCents(string price)
    {
        string[] parts = price.Split('.');
        string fraction = parts.Length == 1 ? "" : parts[1];
        return long.Parse(parts[0]) * 100 + long.Parse((fraction + "00")[..2]);
    }

    private static MergeResult Merge(List<PricedItem> items)
    {
        System.Collections.Generic.Dictionary<string, (int Quantity, long UnitCents)> merged =
            new(StringComparer.Ordinal);
        for (int index = 0; index < items.Count; index++)
        {
            Outcome? error = MergeItem(merged, items[index], index);
            if (error is not null) return new MergeResult(merged, error);
        }
        return new MergeResult(merged, null);
    }

    private static Outcome? MergeItem(
        Dictionary<string, (int Quantity, long UnitCents)> merged, PricedItem priced, int index)
    {
        string sku = priced.Item.Sku;
        if (!merged.TryGetValue(sku, out var prior))
        {
            merged.Add(sku, (priced.Item.Qty, priced.UnitCents));
            return null;
        }
        return Combine(merged, sku, prior, priced, index);
    }

    private static Outcome? Combine(
        Dictionary<string, (int Quantity, long UnitCents)> merged, string sku,
        (int Quantity, long UnitCents) prior, PricedItem priced, int index)
    {
        if (prior.UnitCents != priced.UnitCents) return new QuoteError("PRICE_CONFLICT", index);
        int combined = prior.Quantity + priced.Item.Qty;
        if (combined > 1000) return new QuoteError("BAD_QTY", index);
        merged[sku] = (combined, prior.UnitCents);
        return null;
    }

    private static Outcome? ValidateOptions(Request request)
    {
        if (request.Tier is not ("basic" or "silver" or "gold"))
            return new QuoteError("BAD_TIER", null);
        if (request.Coupon.Length != 0 && !CouponPattern.IsMatch(request.Coupon))
            return new QuoteError("BAD_COUPON", null);
        if (request.Region is not ("EU" or "US" or "ASIA"))
            return new QuoteError("BAD_REGION", null);
        return null;
    }

    private static Pricing BuildPricing(Dictionary<string, (int Quantity, long UnitCents)> merged)
    {
        Line[] lines = PriceLines(merged);
        long subtotal = 0;
        foreach (Line line in lines) subtotal += line.LineCents;
        return new Pricing(lines, subtotal, 0, 0, 0, 0, 0);
    }

    private static Line[] PriceLines(Dictionary<string, (int Quantity, long UnitCents)> merged)
    {
        var lines = new List<Line>();
        foreach (var entry in System.Linq.Enumerable.OrderBy(
            merged, pair => pair.Key, StringComparer.Ordinal))
        {
            long lineCents = entry.Value.UnitCents * entry.Value.Quantity;
            lines.Add(new Line(entry.Key, entry.Value.Quantity, entry.Value.UnitCents, lineCents));
        }
        return lines.ToArray();
    }

    private static Pricing ApplyTier(Pricing pricing, string tier)
    {
        long discount = ScaleHalfUp((BigInteger)pricing.Subtotal * TierBasisPoints(tier), 10000);
        return pricing with { TierDiscount = discount, Net = pricing.Subtotal - discount };
    }

    private static long TierBasisPoints(string tier)
    {
        if (tier == "gold") return 1000;
        if (tier == "silver") return 500;
        return 0;
    }

    private static long ScaleHalfUp(BigInteger numerator, long denominator)
    {
        System.Numerics.BigInteger quotient = System.Numerics.BigInteger.DivRem(
            numerator, denominator, out System.Numerics.BigInteger remainder);
        return (long)quotient + (remainder * 2 >= denominator ? 1 : 0);
    }

    private static Pricing ApplyCoupon(Pricing pricing, string coupon)
    {
        long discount = 0;
        if (coupon.StartsWith("PCT", StringComparison.Ordinal))
        {
            long percentage = long.Parse(coupon[3..]);
            discount = ScaleHalfUp((BigInteger)pricing.Net * percentage, 100);
        }
        else if (coupon.StartsWith("FIXED", StringComparison.Ordinal))
        {
            discount = System.Math.Min(long.Parse(coupon[5..]) * 100, pricing.Net);
        }
        return pricing with { CouponDiscount = discount, Net = pricing.Net - discount };
    }

    private static Pricing ApplyShipping(Pricing pricing, string region, string coupon)
    {
        (long Base, long Threshold) terms = region switch
        {
            "EU" => (800, 10000),
            "US" => (500, 7500),
            _ => (1200, 15000)
        };
        bool waived = coupon == "FREESHIP" || pricing.Net >= terms.Threshold;
        return pricing with { Shipping = waived ? 0 : terms.Base };
    }

    private static Pricing ApplyTax(Pricing pricing, string region)
    {
        long basisPoints = region switch { "EU" => 2000, "US" => 700, _ => 1000 };
        return pricing with { Tax = ScaleHalfUp((BigInteger)pricing.Net * basisPoints, 10000) };
    }

    private static Quote Finish(Pricing pricing)
    {
        long total = pricing.Net + pricing.Shipping + pricing.Tax;
        return new Quote(pricing.Lines, pricing.Subtotal, pricing.TierDiscount,
            pricing.CouponDiscount, pricing.Shipping, pricing.Tax, total, AppliedLabels(pricing));
    }

    private static string[] AppliedLabels(Pricing pricing)
    {
        var applied = new List<string>();
        if (pricing.TierDiscount > 0) applied.Add("tier");
        if (pricing.CouponDiscount > 0) applied.Add("coupon");
        if (pricing.Shipping == 0) applied.Add("free-shipping");
        if (pricing.Tax > 0) applied.Add("tax");
        return applied.ToArray();
    }
}
