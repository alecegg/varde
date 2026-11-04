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
    record Amounts(long subtotal, long tier, long coupon, long net) {}

    private static final Pattern SKU = Pattern.compile("[A-Z0-9-]{3,12}");
    private static final Pattern PRICE = Pattern.compile("[0-9]{1,6}(\\.[0-9]{1,2})?");
    private static final Pattern COUPON = Pattern.compile(
            "(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)");

    /** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
    public static Object solution(Request request) {
        Normalized data = normalise(request);
        QuoteError error = validate(data);
        if (error != null) return error;
        TreeMap<String, long[]> merged = mergeItems(data.items());
        Amounts amounts = priceLines(merged, data.tier(), data.coupon());
        return finish(merged, amounts, data);
    }

    private static Normalized normalise(Request request) {
        List<RawItem> items = new ArrayList<>();
        for (RawItem item : request.items()) {
            String sku = item.sku().strip().toUpperCase(Locale.ROOT);
            items.add(new RawItem(sku, item.qty(), item.price()));
        }
        return new Normalized(items, request.tier().strip().toLowerCase(Locale.ROOT),
                request.coupon().strip().toUpperCase(Locale.ROOT),
                request.region().strip().toUpperCase(Locale.ROOT));
    }

    private static QuoteError validate(Normalized data) {
        if (data.items().isEmpty()) return new QuoteError("EMPTY_ORDER", null);
        if (data.items().size() > 50) return new QuoteError("TOO_MANY_ITEMS", null);
        QuoteError error = validateRows(data.items());
        if (error != null) return error;
        error = validateDuplicates(data.items());
        if (error != null) return error;
        return validateOptions(data.tier(), data.coupon(), data.region());
    }

    private static QuoteError validateRows(List<RawItem> items) {
        for (int index = 0; index < items.size(); index++) {
            RawItem item = items.get(index);
            QuoteError error = itemError(item, index);
            if (error != null) return error;
            if (cents(item.price()) == null) return new QuoteError("BAD_PRICE", index);
        }
        return null;
    }

    private static QuoteError itemError(RawItem item, int index) {
        if (!SKU.matcher(item.sku()).matches()) return new QuoteError("BAD_SKU", index);
        if (item.qty() < 1 || item.qty() > 1000) return new QuoteError("BAD_QTY", index);
        return null;
    }

    private static QuoteError validateDuplicates(List<RawItem> items) {
        Map<String, long[]> seen = new HashMap<>();
        for (int index = 0; index < items.size(); index++) {
            RawItem item = items.get(index);
            QuoteError error = mergeDuplicate(seen, item, index, cents(item.price()));
            if (error != null) return error;
        }
        return null;
    }

    private static QuoteError mergeDuplicate(Map<String, long[]> seen, RawItem item, int index,
            long unitCents) {
        long[] previous = seen.get(item.sku());
        if (previous == null) {
            seen.put(item.sku(), new long[]{item.qty(), unitCents});
            return null;
        }
        if (previous[1] != unitCents) return new QuoteError("PRICE_CONFLICT", index);
        previous[0] += item.qty();
        if (previous[0] > 1000) return new QuoteError("BAD_QTY", index);
        return null;
    }

    private static QuoteError validateOptions(String tier, String coupon, String region) {
        if (!Set.of("basic", "silver", "gold").contains(tier)) {
            return new QuoteError("BAD_TIER", null);
        }
        if (!coupon.isEmpty() && !COUPON.matcher(coupon).matches()) {
            return new QuoteError("BAD_COUPON", null);
        }
        if (!Set.of("EU", "US", "ASIA").contains(region)) {
            return new QuoteError("BAD_REGION", null);
        }
        return null;
    }

    private static Long cents(String text) {
        if (!PRICE.matcher(text).matches()) return null;
        String[] parts = text.split("\\.", -1);
        long wholeCents = Long.parseLong(parts[0]) * 100;
        long fractionCents = parts.length == 1 ? 0
                : Long.parseLong((parts[1] + "00").substring(0, 2));
        long totalCents = wholeCents + fractionCents;
        return totalCents == 0 ? null : totalCents;
    }

    private static TreeMap<String, long[]> mergeItems(List<RawItem> items) {
        TreeMap<String, long[]> merged = new TreeMap<>();
        for (RawItem item : items) {
            long[] previous = merged.get(item.sku());
            if (previous == null) {
                merged.put(item.sku(), new long[]{item.qty(), cents(item.price())});
            } else {
                previous[0] += item.qty();
            }
        }
        return merged;
    }

    private static Amounts priceLines(TreeMap<String, long[]> merged, String tier, String coupon) {
        long subtotal = 0;
        for (long[] item : merged.values()) subtotal += item[0] * item[1];
        long basisPoints = tier.equals("silver") ? 500 : tier.equals("gold") ? 1000 : 0;
        long tierDiscount = round(subtotal, basisPoints, 10000);
        long afterTier = subtotal - tierDiscount;
        long couponCut = couponDiscount(afterTier, coupon);
        return new Amounts(subtotal, tierDiscount, couponCut, afterTier - couponCut);
    }

    private static long couponDiscount(long net, String coupon) {
        if (coupon.startsWith("PCT")) return round(net, Long.parseLong(coupon.substring(3)), 100);
        if (coupon.startsWith("FIXED")) {
            return Math.min(net, Long.parseLong(coupon.substring(5)) * 100);
        }
        return 0;
    }

    private static long round(long value, long rate, long divisor) {
        return (value * rate * 2 + divisor) / (2 * divisor);
    }

    private static Object finish(TreeMap<String, long[]> merged, Amounts amounts, Normalized data) {
        List<Line> lines = quoteLines(merged);
        long shipping = shippingFor(amounts.net(), data);
        long tax = taxFor(amounts.net(), data.region());
        List<String> names = applied(amounts, shipping, tax);
        return new Quote(lines, amounts.subtotal(), amounts.tier(), amounts.coupon(), shipping,
                tax, amounts.net() + shipping + tax, names);
    }

    private static List<Line> quoteLines(TreeMap<String, long[]> merged) {
        List<Line> lines = new ArrayList<>();
        for (Map.Entry<String, long[]> entry : merged.entrySet()) {
            long quantity = entry.getValue()[0];
            long unitCents = entry.getValue()[1];
            lines.add(new Line(entry.getKey(), (int) quantity, unitCents, quantity * unitCents));
        }
        return lines;
    }

    private static long shippingFor(long net, Normalized data) {
        long base;
        long threshold;
        if (data.region().equals("EU")) {
            base = 800;
            threshold = 10000;
        } else if (data.region().equals("US")) {
            base = 500;
            threshold = 7500;
        } else {
            base = 1200;
            threshold = 15000;
        }
        boolean waived = data.coupon().equals("FREESHIP") || net >= threshold;
        return waived ? 0 : base;
    }

    private static long taxFor(long net, String region) {
        long basisPoints = region.equals("EU") ? 2000 : region.equals("US") ? 700 : 1000;
        return round(net, basisPoints, 10000);
    }

    private static List<String> applied(Amounts amounts, long shipping, long tax) {
        List<String> names = new ArrayList<>();
        if (amounts.tier() > 0) names.add("tier");
        if (amounts.coupon() > 0) names.add("coupon");
        if (shipping == 0) names.add("free-shipping");
        if (tax > 0) names.add("tax");
        return names;
    }
}
