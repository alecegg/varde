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

    private static readonly System.Text.RegularExpressions.Regex SkuPattern = new(
        @"\A[A-Z0-9-]{3,12}\z", RegexOptions.CultureInvariant);
    private static readonly Regex PricePattern = new(
        @"\A[0-9]{1,6}(\.[0-9]{1,2})?\z", RegexOptions.CultureInvariant);
    private static readonly Regex CouponPattern = new(
        @"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// Quote normalized order lines with discounts, shipping, tax, and applied adjustments.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Request normalized = Normalize(request);
        Outcome? failure = Validate(normalized);
        if (failure is not null) return failure;
        System.Collections.Generic.Dictionary<string, (int Qty, long Cents)> merged =
            Merge(normalized.Items, out failure);
        if (failure is not null) return failure;
        failure = OptionError(normalized);
        if (failure is not null) return failure;
        Line[] lines = PriceLines(merged);
        return Finish(lines, normalized);
    }

    private static Request Normalize(Request request) => new(
        request.Items.Select(row => new Item(
            row.Sku.Trim().ToUpperInvariant(), row.Qty, row.Price)).ToArray(),
        request.Tier.Trim().ToLowerInvariant(), request.Coupon.Trim().ToUpperInvariant(),
        request.Region.Trim().ToUpperInvariant());

    private static Outcome? Validate(Request request)
    {
        if (request.Items.Length == 0) return new QuoteError("EMPTY_ORDER", null);
        if (request.Items.Length > 50) return new QuoteError("TOO_MANY_ITEMS", null);
        for (int index = 0; index < request.Items.Length; index++)
        {
            Item row = request.Items[index];
            if (!SkuPattern.IsMatch(row.Sku)) return new QuoteError("BAD_SKU", index);
            if (row.Qty < 1 || row.Qty > 1000) return new QuoteError("BAD_QTY", index);
            if (ParsePrice(row.Price) is null) return new QuoteError("BAD_PRICE", index);
        }
        return null;
    }

    private static Outcome? OptionError(Request request)
    {
        if (request.Tier is not ("basic" or "silver" or "gold"))
            return new QuoteError("BAD_TIER", null);
        if (request.Coupon != "" && !CouponPattern.IsMatch(request.Coupon))
            return new QuoteError("BAD_COUPON", null);
        if (request.Region is not ("EU" or "US" or "ASIA"))
            return new QuoteError("BAD_REGION", null);
        return null;
    }

    private static long? ParsePrice(string text)
    {
        if (!PricePattern.IsMatch(text)) return null;
        string[] parts = text.Split('.');
        string fraction = parts.Length == 1 ? "" : parts[1];
        long cents = long.Parse(parts[0]) * 100 + long.Parse((fraction + "00")[..2]);
        return cents > 0 ? cents : null;
    }

    private static Dictionary<string, (int Qty, long Cents)> Merge(
        Item[] items, out Outcome? failure)
    {
        var merged = new Dictionary<string, (int Qty, long Cents)>(System.StringComparer.Ordinal);
        failure = null;
        for (int index = 0; index < items.Length; index++)
        {
            failure = MergeItem(merged, items[index], index);
            if (failure is not null) return merged;
        }
        return merged;
    }

    private static Outcome? MergeItem(
        Dictionary<string, (int Qty, long Cents)> merged,
        Item item,
        int index)
    {
        long cents = ParsePrice(item.Price)!.Value;
        if (!merged.TryGetValue(item.Sku, out var prior))
        {
            merged.Add(item.Sku, (item.Qty, cents));
            return null;
        }
        if (prior.Cents != cents) return new QuoteError("PRICE_CONFLICT", index);
        int quantity = prior.Qty + item.Qty;
        if (quantity > 1000) return new QuoteError("BAD_QTY", index);
        merged[item.Sku] = (quantity, cents);
        return null;
    }

    private static Line[] PriceLines(Dictionary<string, (int Qty, long Cents)> merged) =>
        merged.OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => new Line(pair.Key, pair.Value.Qty, pair.Value.Cents,
                pair.Value.Cents * pair.Value.Qty)).ToArray();

    private static long RoundHalfUp(BigInteger numerator, long denominator)
    {
        System.Numerics.BigInteger quotient = System.Numerics.BigInteger.DivRem(
            numerator, denominator, out System.Numerics.BigInteger remainder);
        return (long)(quotient + (remainder * 2 >= denominator ? 1 : 0));
    }

    private static long TierRate(string tier) => tier switch
    {
        "gold" => 1000,
        "silver" => 500,
        _ => 0
    };

    private static (long Rate, long BaseShipping, long Threshold) RegionRates(
        string region) => region switch
    {
        "EU" => (2000, 800, 10000), "US" => (700, 500, 7500), _ => (1000, 1200, 15000)
    };

    private static Quote Finish(Line[] lines, Request request)
    {
        long subtotal = System.Linq.Enumerable.Sum(lines, line => line.LineCents);
        long tierDiscount = RoundHalfUp((BigInteger)subtotal * TierRate(request.Tier), 10000);
        long afterTier = subtotal - tierDiscount;
        long couponDiscount = CouponDiscount(request.Coupon, afterTier);
        long net = afterTier - couponDiscount;
        var (taxRate, baseShipping, threshold) = RegionRates(request.Region);
        long shipping = ShippingFor(request.Coupon, net, baseShipping, threshold);
        long tax = TaxAmount(net, taxRate);
        return new Quote(lines, subtotal, tierDiscount, couponDiscount, shipping, tax,
            net + shipping + tax, Applied(tierDiscount, couponDiscount, shipping, tax));
    }

    private static long TaxAmount(long net, long rate)
    {
        System.Numerics.BigInteger numerator = (System.Numerics.BigInteger)net * rate;
        long tax = RoundHalfUp(numerator, 10000);
        return tax;
    }

    private static long ShippingFor(string coupon, long net, long baseShipping, long threshold)
    {
        bool couponWaives = coupon == "FREESHIP";
        bool amountWaives = net >= threshold;
        return couponWaives || amountWaives ? 0 : baseShipping;
    }

    private static long CouponDiscount(string coupon, long basis)
    {
        if (coupon.StartsWith("PCT", StringComparison.Ordinal))
            return RoundHalfUp((BigInteger)basis * long.Parse(coupon[3..]), 100);
        if (coupon.StartsWith("FIXED", StringComparison.Ordinal))
            return Math.Min(long.Parse(coupon[5..]) * 100, basis);
        return 0;
    }

    private static string[] Applied(long tier, long coupon, long shipping, long tax)
    {
        var result = new List<string>();
        if (tier > 0) result.Add("tier");
        if (coupon > 0) result.Add("coupon");
        if (shipping == 0) result.Add("free-shipping");
        if (tax > 0) result.Add("tax");
        return result.ToArray();
    }
}
