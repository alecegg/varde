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
        Normalized n = normalisedRequest(request);
        QuoteError e = validateOrder(n);
        if (e != null) return e;
        TreeMap<String, long[]> m = mergedItems(n.items());
        Amounts a = calculateAmounts(m, n);
        return assembleQuote(m, a, n);
    }
    private static Normalized normalisedRequest(Request r) {
        return new Normalized(normalisedItems(r.items()), r.tier().strip().toLowerCase(Locale.ROOT),
                upperTrimmed(r.coupon()), upperTrimmed(r.region()));
    }
    private static List<RawItem> normalisedItems(List<RawItem> xs) {
        List<RawItem> out = new ArrayList<>();
        for (RawItem x : xs) out.add(normalisedItem(x));
        return out;
    }
    private static RawItem normalisedItem(RawItem x) {
        return new RawItem(upperTrimmed(x.sku()), x.qty(), x.price());
    }
    private static String upperTrimmed(String s) { return s.strip().toUpperCase(Locale.ROOT); }
    private static QuoteError errorResult(String s, Integer i) { return new QuoteError(s, i); }
    private static QuoteError validateOrder(Normalized n) {
        if (n.items().isEmpty()) return errorResult("EMPTY_ORDER", null);
        if (n.items().size() > 50) return errorResult("TOO_MANY_ITEMS", null);
        QuoteError rows = itemErrors(n.items());
        if (rows != null) return rows;
        return validateAfterRows(n);
    }
    private static QuoteError validateAfterRows(Normalized n) {
        QuoteError e = duplicateError(n.items());
        return e == null ? optionError(n) : e;
    }
    private static QuoteError itemErrors(List<RawItem> xs) {
        for (int i = 0; i < xs.size(); i++) {
            QuoteError e = itemErrorAt(xs.get(i), i);
            if (e != null) return e;
        }
        return null;
    }
    private static QuoteError itemErrorAt(RawItem x, int i) {
        if (!validSku(x.sku())) return errorResult("BAD_SKU", i);
        if (!validQuantity(x.qty())) return errorResult("BAD_QTY", i);
        return validPrice(x.price()) ? null : errorResult("BAD_PRICE", i);
    }
    private static boolean validSku(String s) { return skuMatches(s); }
    private static boolean skuMatches(String s) { return SKU.matcher(s).matches(); }
    private static boolean validQuantity(int q) { return quantityInRange(q); }
    private static boolean quantityInRange(int q) { return q >= 1 && q <= 1000; }
    private static boolean validPrice(String p) { return priceMatches(p); }
    private static boolean priceMatches(String p) {
        return PRICE.matcher(p).matches() && priceCents(p) > 0;
    }
    private static long priceCents(String s) {
        String[] p = s.split("\\.", -1);
        return Long.parseLong(p[0]) * 100 + (p.length == 1 ? 0 :
                Long.parseLong((p[1] + "00").substring(0, 2)));
    }
    private static QuoteError duplicateError(List<RawItem> xs) {
        Map<String, long[]> seen = new HashMap<>();
        for (int i = 0; i < xs.size(); i++) {
            RawItem x = xs.get(i);
            QuoteError e = mergeDuplicate(seen, x, i);
            if (e != null) return e;
        }
        return null;
    }
    private static QuoteError mergeDuplicate(Map<String, long[]> seen, RawItem x, int i) {
        long[] old = seen.get(x.sku());
        if (old == null) return rememberFirstItem(seen, x);
        return validateDuplicatePrice(old, x, i);
    }
    private static QuoteError rememberFirstItem(Map<String, long[]> seen, RawItem x) {
        seen.put(x.sku(), new long[]{x.qty(), priceCents(x.price())});
        return null;
    }
    private static QuoteError validateDuplicatePrice(long[] old, RawItem x, int i) {
        if (old[1] != priceCents(x.price())) return errorResult("PRICE_CONFLICT", i);
        old[0] += x.qty();
        return old[0] > 1000 ? errorResult("BAD_QTY", i) : null;
    }
    private static QuoteError optionError(Normalized n) {
        QuoteError e = tierValidationError(n.tier());
        if (e != null) return e;
        e = couponValidationError(n.coupon());
        if (e != null) return e;
        return regionValidationError(n.region());
    }
    private static QuoteError tierValidationError(String t) {
        return Set.of("basic", "silver", "gold").contains(t) ? null : errorResult("BAD_TIER", null);
    }
    private static QuoteError couponValidationError(String c) {
        return c.isEmpty() || COUPON.matcher(c).matches() ? null : errorResult("BAD_COUPON", null);
    }
    private static QuoteError regionValidationError(String r) {
        return Set.of("EU", "US", "ASIA").contains(r) ? null : errorResult("BAD_REGION", null);
    }
    private static TreeMap<String, long[]> mergedItems(List<RawItem> xs) {
        TreeMap<String, long[]> out = new TreeMap<>();
        for (RawItem x : xs) mergeItemInto(out, x);
        return out;
    }
    private static void mergeItemInto(TreeMap<String, long[]> m, RawItem x) {
        long[] old = m.get(x.sku());
        if (old == null) m.put(x.sku(), new long[]{x.qty(), priceCents(x.price())});
        else old[0] += x.qty();
    }
    private static Amounts calculateAmounts(TreeMap<String, long[]> m, Normalized n) {
        long amount = subtotalFor(m);
        long td = roundHalfUp(amount, tierBasisPoints(n.tier()), 10000);
        long net = amount - td;
        long cd = couponCut(net, n.coupon());
        return new Amounts(amount, td, cd, net - cd);
    }
    private static long subtotalFor(TreeMap<String, long[]> m) {
        return sumLineAmounts(m.values());
    }
    private static long sumLineAmounts(Iterable<long[]> xs) {
        long n = 0;
        for (long[] x : xs) n += x[0] * x[1];
        return n;
    }
    private static long tierBasisPoints(String t) {
        return t.equals("gold") ? 1000 : t.equals("silver") ? 500 : 0;
    }
    private static long roundHalfUp(long n, long taxBasisPoints, long div) {
        return (n * taxBasisPoints * 2 + div) / (2 * div);
    }
    private static long couponCut(long n, String c) {
        if (c.startsWith("PCT")) return roundHalfUp(n, Long.parseLong(c.substring(3)), 100);
        if (c.startsWith("FIXED")) return Math.min(Long.parseLong(c.substring(5)) * 100, n);
        return 0;
    }
    private static List<Line> quoteLines(TreeMap<String, long[]> m) {
        List<Line> out = new ArrayList<>();
        for (var e : m.entrySet()) out.add(quoteLine(e));
        return out;
    }
    private static Line quoteLine(Map.Entry<String, long[]> e) {
        long[] x = e.getValue();
        return new Line(e.getKey(), (int)x[0], x[1],
                x[0] * x[1]);
    }
    private static long taxBasisPoints(String r) {
        return r.equals("EU") ? 2000 : r.equals("US") ? 700 : 1000;
    }
    private static long baseShipping(String r) {
        return r.equals("EU") ? 800 : r.equals("US") ? 500 : 1200;
    }
    private static long freeShippingThreshold(String r) {
        return r.equals("EU") ? 10000 : r.equals("US") ? 7500 : 15000;
    }
    private static long shippingCharge(Amounts a, Normalized n) {
        return n.coupon().equals("FREESHIP") || a.net() >= freeShippingThreshold(n.region())
                ? 0 : baseShipping(n.region());
    }
    private static List<String> appliedAdjustments(Amounts a, long sh, long tx) {
        List<String> out = new ArrayList<>();
        addTierAdjustment(out, a.tier());
        addCouponAdjustment(out, a.coupon());
        addShippingAdjustment(out, sh);
        addTaxAdjustment(out, tx);
        return out;
    }
    private static void addTierAdjustment(List<String> out, long n) {
        if (n > 0) out.add("tier");
    }
    private static void addCouponAdjustment(List<String> out, long n) {
        if (n > 0) out.add("coupon");
    }
    private static void addShippingAdjustment(List<String> out, long n) {
        if (n == 0) out.add("free-shipping");
    }
    private static void addTaxAdjustment(List<String> out, long n) {
        if (n > 0) out.add("tax");
    }
    private static Quote assembleQuote(TreeMap<String, long[]> m, Amounts a, Normalized n) {
        long sh = shippingCharge(a, n), tx = taxAmount(a, n);
        return quoteResult(quoteLines(m), a, sh, tx);
    }
    private static Quote quoteResult(List<Line> ls, Amounts a, long sh, long tx) {
        return new Quote(ls, a.subtotal(), a.tier(), a.coupon(), sh, tx,
                totalAmount(a.net(), sh, tx), appliedAdjustments(a, sh, tx));
    }
    private static long taxAmount(Amounts a, Normalized n) {
        return roundHalfUp(a.net(), taxBasisPoints(n.region()), 10000);
    }
    private static long totalAmount(long n, long sh, long tx) {
        return n + sh + tx;
    }
}
