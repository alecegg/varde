
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
    private static readonly System.Text.RegularExpressions.Regex PricePattern = new(
        @"\A[0-9]{1,6}(\.[0-9]{1,2})?\z");
    private static readonly System.Text.RegularExpressions.Regex CouponPattern = new(
        @"\A(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)\z");

    /// <summary>
    /// Quote normalized order lines with discounts, shipping, tax, and applied adjustments.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Item[] normalizedItems = new Item[request.Items.Length];
        for (int index = 0; index < request.Items.Length; index++)
        {
            Item source = request.Items[index];
            string normalizedSku = source.Sku.Trim().ToUpperInvariant();
            normalizedItems[index] = new Item(
                normalizedSku, source.Qty, source.Price);
        }
        string tierText = request.Tier.Trim();
        string couponText = request.Coupon.Trim();
        string regionText = request.Region.Trim();
        string tier = tierText.ToLowerInvariant();
        string coupon = couponText.ToUpperInvariant();
        string region = regionText.ToUpperInvariant();
        int itemCount = normalizedItems.Length;
        bool hasNoItems = itemCount == 0;
        bool hasTooManyItems = itemCount > 50;
        if (hasNoItems) return new QuoteError("EMPTY_ORDER", null);
        if (hasTooManyItems) return new QuoteError("TOO_MANY_ITEMS", null);
        var checkedPrices = new long[itemCount];
        for (int index = 0; index < itemCount; index++)
        {
            Item row = normalizedItems[index];
            bool validSku = SkuPattern.IsMatch(row.Sku);
            if (!validSku) return new QuoteError("BAD_SKU", index);
            bool quantityTooSmall = row.Qty < 1;
            bool quantityTooLarge = row.Qty > 1000;
            bool validQuantity = !quantityTooSmall && !quantityTooLarge;
            if (!validQuantity) return new QuoteError("BAD_QTY", index);
            bool validPriceText = PricePattern.IsMatch(row.Price);
            if (!validPriceText) return new QuoteError("BAD_PRICE", index);
            string[] priceParts = row.Price.Split('.');
            string wholeDigits = priceParts[0];
            bool hasFraction = priceParts.Length > 1;
            string fractionDigits = hasFraction ? priceParts[1] : "";
            string centsDigits = (fractionDigits + "00")[..2];
            long wholeCents = long.Parse(wholeDigits) * 100;
            long fractionCents = long.Parse(centsDigits);
            long cents = wholeCents + fractionCents;
            bool positivePrice = cents > 0;
            if (!positivePrice) return new QuoteError("BAD_PRICE", index);
            checkedPrices[index] = cents;
        }
        var quantities = new System.Collections.Generic.Dictionary<string, int>(
            System.StringComparer.Ordinal);
        var unitPrices = new System.Collections.Generic.Dictionary<string, long>(
            System.StringComparer.Ordinal);
        for (int index = 0; index < itemCount; index++)
        {
            Item row = normalizedItems[index];
            long cents = checkedPrices[index];
            bool isNewSku = !unitPrices.TryGetValue(row.Sku, out long firstPrice);
            if (isNewSku)
            {
                unitPrices.Add(row.Sku, cents);
                quantities.Add(row.Sku, row.Qty);
                continue;
            }
            bool priceConflict = firstPrice != cents;
            if (priceConflict) return new QuoteError("PRICE_CONFLICT", index);
            int combinedQuantity = quantities[row.Sku] + row.Qty;
            bool mergedQuantityTooLarge = combinedQuantity > 1000;
            if (mergedQuantityTooLarge) return new QuoteError("BAD_QTY", index);
            quantities[row.Sku] = combinedQuantity;
        }
        bool validTier = tier is "basic" or "silver" or "gold";
        if (!validTier) return new QuoteError("BAD_TIER", null);
        bool couponIsPresent = coupon != "";
        bool validCoupon = !couponIsPresent || CouponPattern.IsMatch(coupon);
        if (!validCoupon)
            return new QuoteError("BAD_COUPON", null);
        bool validRegion = region is "EU" or "US" or "ASIA";
        if (!validRegion) return new QuoteError("BAD_REGION", null);
        var lines = new System.Collections.Generic.List<Line>();
        long subtotal = 0;
        foreach (string sku in System.Linq.Enumerable.OrderBy(
            quantities.Keys, value => value, System.StringComparer.Ordinal))
        {
            int quantity = quantities[sku];
            long unitCents = unitPrices[sku];
            long lineCents = unitCents * quantity;
            subtotal += lineCents;
            lines.Add(new Line(sku, quantity, unitCents, lineCents));
        }
        bool isGoldTier = tier == "gold";
        bool isSilverTier = tier == "silver";
        long tierBasisPoints = isGoldTier ? 1000 : isSilverTier ? 500 : 0;
        System.Numerics.BigInteger tierNumerator =
            (System.Numerics.BigInteger)subtotal * tierBasisPoints;
        System.Numerics.BigInteger tierWhole = System.Numerics.BigInteger.DivRem(
            tierNumerator, 10000, out System.Numerics.BigInteger tierRemainder);
        bool tierRoundsUp = tierRemainder * 2 >= 10000;
        long tierRoundingCents = tierRoundsUp ? 1 : 0;
        long tierDiscount = (long)(tierWhole + tierRoundingCents);
        long afterTier = subtotal - tierDiscount;
        long couponDiscount = 0;
        bool isPercentCoupon = coupon.StartsWith("PCT", System.StringComparison.Ordinal);
        bool isFixedCoupon = coupon.StartsWith("FIXED", System.StringComparison.Ordinal);
        if (isPercentCoupon)
        {
            string percentDigits = coupon[3..];
            long percentage = long.Parse(percentDigits);
            System.Numerics.BigInteger percentNumerator =
                (System.Numerics.BigInteger)afterTier * percentage;
            System.Numerics.BigInteger percentWhole = System.Numerics.BigInteger.DivRem(
                percentNumerator, 100, out System.Numerics.BigInteger percentRemainder);
            bool percentRoundsUp = percentRemainder * 2 >= 100;
            long percentRoundingCents = percentRoundsUp ? 1 : 0;
            couponDiscount = (long)(percentWhole + percentRoundingCents);
        }
        else if (isFixedCoupon)
        {
            string fixedDigits = coupon[5..];
            long fixedDollars = long.Parse(fixedDigits);
            long fixedCents = fixedDollars * 100;
            couponDiscount = System.Math.Min(fixedCents, afterTier);
        }
        long net = afterTier - couponDiscount;
        long taxBasisPoints;
        long baseShipping;
        long freeShippingAt;
        bool isEuropeanRegion = region == "EU";
        bool isUnitedStatesRegion = region == "US";
        if (isEuropeanRegion)
        {
            taxBasisPoints = 2000;
            baseShipping = 800;
            freeShippingAt = 10000;
        }
        else if (isUnitedStatesRegion)
        {
            taxBasisPoints = 700;
            baseShipping = 500;
            freeShippingAt = 7500;
        }
        else
        {
            taxBasisPoints = 1000;
            baseShipping = 1200;
            freeShippingAt = 15000;
        }
        bool couponWaivesShipping = coupon == "FREESHIP";
        bool valueWaivesShipping = net >= freeShippingAt;
        bool waived = couponWaivesShipping || valueWaivesShipping;
        long shipping = waived ? 0 : baseShipping;
        System.Numerics.BigInteger taxNumerator = (System.Numerics.BigInteger)net * taxBasisPoints;
        System.Numerics.BigInteger taxWhole = System.Numerics.BigInteger.DivRem(
            taxNumerator, 10000, out System.Numerics.BigInteger taxRemainder);
        bool taxRoundsUp = taxRemainder * 2 >= 10000;
        long taxRoundingCents = taxRoundsUp ? 1 : 0;
        long tax = (long)(taxWhole + taxRoundingCents);
        var applied = new System.Collections.Generic.List<string>();
        bool tierApplied = tierDiscount > 0;
        if (tierApplied) applied.Add("tier");
        bool couponApplied = couponDiscount > 0;
        if (couponApplied) applied.Add("coupon");
        bool freeShippingApplied = shipping == 0;
        if (freeShippingApplied) applied.Add("free-shipping");
        bool taxApplied = tax > 0;
        if (taxApplied) applied.Add("tax");
        long total = net + shipping + tax;
        return new Quote(lines.ToArray(), subtotal, tierDiscount, couponDiscount, shipping, tax,
            total, applied.ToArray());
    }
}
