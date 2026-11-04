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
        @"\A[A-Z0-9-]{3,12}\z");
    private static readonly Regex PricePattern = new(@"\A[0-9]{1,6}(\.[0-9]{1,2})?\z");
    private static readonly Regex CouponPattern = new(
        @"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z");

    /// <summary>
    /// Quote normalized order lines with discounts, shipping, tax, and applied adjustments.
    /// </summary>
    public static Outcome solution(Request request)
    {
        var normalizedItems = new Item[request.Items.Length];
        for (int index = 0; index < request.Items.Length; index++)
        {
            Item source = request.Items[index];
            string trimmedSku = source.Sku.Trim();
            string normalizedSku = trimmedSku.ToUpperInvariant();
            normalizedItems[index] = new Item(normalizedSku, source.Qty, source.Price);
        }
        string tier = request.Tier.Trim().ToLowerInvariant();
        string coupon = request.Coupon.Trim().ToUpperInvariant();
        string region = request.Region.Trim().ToUpperInvariant();
        if (normalizedItems.Length == 0) return new QuoteError("EMPTY_ORDER", null);
        if (normalizedItems.Length > 50) return new QuoteError("TOO_MANY_ITEMS", null);

        var itemCents = new long[normalizedItems.Length];
        for (int index = 0; index < normalizedItems.Length; index++)
        {
            Item item = normalizedItems[index];
            if (!SkuPattern.IsMatch(item.Sku)) return new QuoteError("BAD_SKU", index);
            if (item.Qty is < 1 or > 1000) return new QuoteError("BAD_QTY", index);
            if (!PricePattern.IsMatch(item.Price)) return new QuoteError("BAD_PRICE", index);
            string[] amountParts = item.Price.Split('.');
            string wholeDigits = amountParts[0];
            string fractionDigits = amountParts.Length == 1 ? "" : amountParts[1];
            string centDigits = (fractionDigits + "00")[..2];
            long wholeCents = long.Parse(wholeDigits) * 100;
            long fractionCents = long.Parse(centDigits);
            long unitCents = wholeCents + fractionCents;
            if (unitCents <= 0) return new QuoteError("BAD_PRICE", index);
            itemCents[index] = unitCents;
        }

        System.Collections.Generic.Dictionary<string, (int Quantity, long UnitCents)> mergedItems =
            new(StringComparer.Ordinal);
        for (int index = 0; index < normalizedItems.Length; index++)
        {
            Item item = normalizedItems[index];
            long unitCents = itemCents[index];
            if (!mergedItems.TryGetValue(item.Sku, out var existing))
            {
                mergedItems.Add(item.Sku, (item.Qty, unitCents));
                continue;
            }
            if (existing.UnitCents != unitCents) return new QuoteError("PRICE_CONFLICT", index);
            int mergedQuantity = existing.Quantity + item.Qty;
            if (mergedQuantity > 1000) return new QuoteError("BAD_QTY", index);
            mergedItems[item.Sku] = (mergedQuantity, unitCents);
        }

        if (tier is not ("basic" or "silver" or "gold")) return new QuoteError("BAD_TIER", null);
        if (coupon.Length != 0 && !CouponPattern.IsMatch(coupon))
            return new QuoteError("BAD_COUPON", null);
        if (region is not ("EU" or "US" or "ASIA")) return new QuoteError("BAD_REGION", null);

        string[] orderedSkus = System.Linq.Enumerable.OrderBy(
            mergedItems.Keys, sku => sku, StringComparer.Ordinal).ToArray();
        var lines = new Line[orderedSkus.Length];
        long subtotal = 0;
        for (int index = 0; index < orderedSkus.Length; index++)
        {
            string sku = orderedSkus[index];
            (int Quantity, long UnitCents) row = mergedItems[sku];
            long lineCents = row.UnitCents * row.Quantity;
            lines[index] = new Line(sku, row.Quantity, row.UnitCents, lineCents);
            subtotal += lineCents;
        }

        long tierBasisPoints;
        if (tier == "gold") tierBasisPoints = 1000;
        else if (tier == "silver") tierBasisPoints = 500;
        else tierBasisPoints = 0;
        System.Numerics.BigInteger tierNumerator =
            (System.Numerics.BigInteger)subtotal * tierBasisPoints;
        System.Numerics.BigInteger tierWhole = System.Numerics.BigInteger.DivRem(
            tierNumerator, 10000, out System.Numerics.BigInteger tierRemainder);
        bool tierRoundsUp = tierRemainder * 2 >= 10000;
        long tierDiscount = (long)tierWhole + (tierRoundsUp ? 1 : 0);
        long afterTier = subtotal - tierDiscount;

        long couponDiscount = 0;
        bool percentCoupon = coupon.StartsWith("PCT", StringComparison.Ordinal);
        if (percentCoupon)
        {
            string percentDigits = coupon[3..];
            long percentage = long.Parse(percentDigits);
            System.Numerics.BigInteger couponNumerator =
                (System.Numerics.BigInteger)afterTier * percentage;
            System.Numerics.BigInteger couponWhole = System.Numerics.BigInteger.DivRem(
                couponNumerator, 100, out System.Numerics.BigInteger couponRemainder);
            bool couponRoundsUp = couponRemainder * 2 >= 100;
            couponDiscount = (long)couponWhole + (couponRoundsUp ? 1 : 0);
        }
        else
        {
            bool fixedCoupon = coupon.StartsWith("FIXED", StringComparison.Ordinal);
            if (fixedCoupon)
            {
                string fixedDigits = coupon[5..];
                long fixedDollars = long.Parse(fixedDigits);
                long fixedCents = fixedDollars * 100;
                couponDiscount = System.Math.Min(fixedCents, afterTier);
            }
        }
        long net = afterTier - couponDiscount;

        long taxBasisPoints;
        long shippingBase;
        long freeShippingAt;
        if (region == "EU")
        {
            taxBasisPoints = 2000;
            shippingBase = 800;
            freeShippingAt = 10000;
        }
        else if (region == "US")
        {
            taxBasisPoints = 700;
            shippingBase = 500;
            freeShippingAt = 7500;
        }
        else
        {
            taxBasisPoints = 1000;
            shippingBase = 1200;
            freeShippingAt = 15000;
        }
        bool couponWaivesShipping = coupon == "FREESHIP";
        bool valueWaivesShipping = net >= freeShippingAt;
        long shipping = couponWaivesShipping || valueWaivesShipping ? 0 : shippingBase;
        System.Numerics.BigInteger taxNumerator = (System.Numerics.BigInteger)net * taxBasisPoints;
        System.Numerics.BigInteger taxWhole = System.Numerics.BigInteger.DivRem(
            taxNumerator, 10000, out System.Numerics.BigInteger taxRemainder);
        bool taxRoundsUp = taxRemainder * 2 >= 10000;
        long tax = (long)taxWhole + (taxRoundsUp ? 1 : 0);

        var applied = new List<string>();
        bool tierApplied = tierDiscount > 0;
        if (tierApplied) applied.Add("tier");
        bool couponApplied = couponDiscount > 0;
        if (couponApplied) applied.Add("coupon");
        bool freeShippingApplied = shipping == 0;
        if (freeShippingApplied) applied.Add("free-shipping");
        bool taxApplied = tax > 0;
        if (taxApplied) applied.Add("tax");
        long total = net + shipping + tax;
        return new Quote(lines, subtotal, tierDiscount, couponDiscount, shipping, tax,
            total, applied.ToArray());
    }
}
