import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;

public class solution {
    record RawItem(String sku, int qty, String price) {}
    record Request(List<RawItem> items, String tier, String coupon, String region) {}
    record Line(String sku, int qty, long unit_cents, long line_cents) {}
    record Quote(List<Line> lines, long subtotal, long tier_discount, long coupon_discount,
                 long shipping, long tax, long total, List<String> applied) {}
    record QuoteError(String error, Integer index) {}
    record Normalized(List<RawItem> items, String tier, String coupon, String region) {}
    record Adjustment(String name, long cents, boolean active) {}
    record Amounts(long subtotal, Adjustment tier, Adjustment coupon, long net) {}
    record Rates(long tax, long shipping, long threshold) {}

    private static final Pattern SKU = Pattern.compile("[A-Z0-9-]{3,12}");
    private static final Pattern PRICE = Pattern.compile("[0-9]{1,6}(\\.[0-9]{1,2})?");
    private static final Pattern COUPON = Pattern.compile(
            "(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)");
    private static final Locale ROOT = Locale.ROOT;
    private static final Set<String> TIERS = Set.of("basic", "silver", "gold");
    private static final Set<String> REGIONS = Set.of("EU", "US", "ASIA");

    /** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
    public static Object solution(Request request) {
        Normalized data = normalise(request);
        QuoteError error = validateAll(data);
        if (error != null) return error;
        TreeMap<String, long[]> merged = mergeItems(data.items());
        Amounts amounts = priceAll(merged, data.tier(), data.coupon());
        return assembleQuote(merged, amounts, data, ratesFor(data.region()));
    }

    private static Normalized normalise(Request request) {
        List<RawItem> items = new ArrayList<>();
        for (RawItem item : request.items()) {
            String sku = item.sku().strip().toUpperCase(ROOT);
            items.add(new RawItem(sku, item.qty(), item.price()));
        }
        return new Normalized(items, request.tier().strip().toLowerCase(ROOT),
                request.coupon().strip().toUpperCase(ROOT),
                request.region().strip().toUpperCase(ROOT));
    }

    private static QuoteError validateAll(Normalized data) {
        if (data.items().isEmpty()) return new QuoteError("EMPTY_ORDER", null);
        if (data.items().size() > 50) return new QuoteError("TOO_MANY_ITEMS", null);
        QuoteError error = validateItems(data.items());
        if (error != null) return error;
        error = checkDuplicates(data.items());
        if (error != null) return error;
        return checkOptions(data);
    }

    private static QuoteError validateItems(List<RawItem> items) {
        for (int index = 0; index < items.size(); index++) {
            QuoteError error = checkItem(items.get(index), index);
            if (error != null) return error;
        }
        return null;
    }

    private static QuoteError checkItem(RawItem item, int index) {
        QuoteError error = checkSkuQuantity(item, index);
        if (error != null) return error;
        return priceCents(item.price()) == null ? new QuoteError("BAD_PRICE", index) : null;
    }

    private static QuoteError checkSkuQuantity(RawItem item, int index) {
        boolean skuMatches = SKU.matcher(item.sku()).matches();
        if (!skuMatches) return new QuoteError("BAD_SKU", index);
        boolean quantityInRange = item.qty() >= 1 && item.qty() <= 1000;
        if (!quantityInRange) return new QuoteError("BAD_QTY", index);
        return null;
    }

    private static Long priceCents(String text) {
        boolean priceMatches = PRICE.matcher(text).matches();
        if (!priceMatches) return null;
        String[] parts = text.split("\\.", -1);
        long wholeCents = Long.parseLong(parts[0]) * 100;
        long fractionCents = parts.length == 1 ? 0
                : Long.parseLong((parts[1] + "00").substring(0, 2));
        long totalCents = wholeCents + fractionCents;
        return totalCents == 0 ? null : totalCents;
    }

    private static QuoteError checkDuplicates(List<RawItem> items) {
        Map<String, long[]> seen = new HashMap<>();
        for (int index = 0; index < items.size(); index++) {
            RawItem item = items.get(index);
            QuoteError error = mergeDuplicate(seen, item, index, priceCents(item.price()));
            if (error != null) return error;
        }
        return null;
    }

    private static QuoteError mergeDuplicate(Map<String, long[]> seen, RawItem item, int index,
            long unitCents) {
        long[] previous = seen.putIfAbsent(item.sku(), new long[]{item.qty(), unitCents});
        if (previous == null) return null;
        if (previous[1] != unitCents) return new QuoteError("PRICE_CONFLICT", index);
        long combined = previous[0] + item.qty();
        if (combined > 1000) return new QuoteError("BAD_QTY", index);
        previous[0] = combined;
        return null;
    }

    private static QuoteError checkOptions(Normalized data) {
        if (!TIERS.contains(data.tier())) return new QuoteError("BAD_TIER", null);
        boolean couponSupported = data.coupon().isEmpty()
                || COUPON.matcher(data.coupon()).matches();
        if (!couponSupported) return new QuoteError("BAD_COUPON", null);
        if (!REGIONS.contains(data.region())) return new QuoteError("BAD_REGION", null);
        return null;
    }

    private static TreeMap<String, long[]> mergeItems(List<RawItem> items) {
        TreeMap<String, long[]> merged = new TreeMap<>();
        for (RawItem item : items) {
            long[] previous = merged.get(item.sku());
            if (previous == null) {
                merged.put(item.sku(), new long[]{item.qty(), priceCents(item.price())});
            } else {
                previous[0] += item.qty();
            }
        }
        return merged;
    }

    private static Amounts priceAll(TreeMap<String, long[]> merged, String tier, String coupon) {
        long subtotal = 0;
        for (long[] item : merged.values()) subtotal += item[0] * item[1];
        Adjustment tierCut = tierAdjustment(subtotal, tier);
        long afterTier = subtotal - tierCut.cents();
        Adjustment couponCut = couponAdjustment(afterTier, coupon);
        return new Amounts(subtotal, tierCut, couponCut, afterTier - couponCut.cents());
    }

    private static Adjustment tierAdjustment(long subtotal, String tier) {
        long basisPoints = tier.equals("silver") ? 500 : tier.equals("gold") ? 1000 : 0;
        long discount = roundHalfUp(subtotal, basisPoints, 10000);
        return new Adjustment("tier", discount, discount > 0);
    }

    private static Adjustment couponAdjustment(long afterTier, String coupon) {
        long discount = 0;
        if (coupon.startsWith("PCT")) {
            discount = roundHalfUp(afterTier, Long.parseLong(coupon.substring(3)), 100);
        } else if (coupon.startsWith("FIXED")) {
            discount = Math.min(afterTier, Long.parseLong(coupon.substring(5)) * 100);
        }
        return new Adjustment("coupon", discount, discount > 0);
    }

    private static long roundHalfUp(long value, long rate, long divisor) {
        return (value * rate * 2 + divisor) / (2 * divisor);
    }

    private static Object assembleQuote(TreeMap<String, long[]> merged, Amounts amounts,
            Normalized data, Rates rates) {
        List<Line> lines = makeLines(merged);
        Adjustment shipping = shippingAdjustment(amounts.net(), data, rates);
        Adjustment tax = taxAdjustment(amounts.net(), rates);
        return quoteResult(lines, amounts, shipping, tax);
    }

    private static Quote quoteResult(List<Line> lines, Amounts amounts, Adjustment shipping,
            Adjustment tax) {
        List<String> applied = collectApplied(amounts.tier(), amounts.coupon(), shipping, tax);
        long total = amounts.net() + shipping.cents() + tax.cents();
        return new Quote(lines, amounts.subtotal(), amounts.tier().cents(),
                amounts.coupon().cents(), shipping.cents(), tax.cents(), total, applied);
    }

    private static List<Line> makeLines(TreeMap<String, long[]> merged) {
        List<Line> lines = new ArrayList<>();
        for (Map.Entry<String, long[]> entry : merged.entrySet()) {
            long quantity = entry.getValue()[0];
            long unitCents = entry.getValue()[1];
            lines.add(new Line(entry.getKey(), (int) quantity, unitCents, quantity * unitCents));
        }
        return lines;
    }

    private static Adjustment shippingAdjustment(long net, Normalized data, Rates rates) {
        boolean waived = data.coupon().equals("FREESHIP") || net >= rates.threshold();
        long cents = waived ? 0 : rates.shipping();
        return new Adjustment("free-shipping", cents, cents == 0);
    }

    private static Adjustment taxAdjustment(long net, Rates rates) {
        long discount = roundHalfUp(net, rates.tax(), 10000);
        return new Adjustment("tax", discount, discount > 0);
    }

    private static List<String> collectApplied(Adjustment... adjustments) {
        List<String> names = new ArrayList<>();
        for (Adjustment adjustment : adjustments) {
            if (adjustment.active()) names.add(adjustment.name());
        }
        return names;
    }

    private static Rates ratesFor(String region) {
        if (region.equals("EU")) return new Rates(2000, 800, 10000);
        if (region.equals("US")) return new Rates(700, 500, 7500);
        return new Rates(1000, 1200, 15000);
    }
}
