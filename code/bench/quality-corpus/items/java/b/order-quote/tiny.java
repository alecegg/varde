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
        Normalized n = norm(request);
        QuoteError e = check(n);
        if (e != null) return e;
        TreeMap<String, long[]> m = merge(n.items());
        Amounts a = amounts(m, n);
        return done(m, a, n);
    }
    private static Normalized norm(Request r) {
        return new Normalized(ni(r.items()), r.tier().strip().toLowerCase(Locale.ROOT),
                up(r.coupon()), up(r.region()));
    }
    private static List<RawItem> ni(List<RawItem> xs) {
        List<RawItem> out = new ArrayList<>();
        for (RawItem x : xs) out.add(none(x));
        return out;
    }
    private static RawItem none(RawItem x) {
        return new RawItem(up(x.sku()), x.qty(), x.price());
    }
    private static String up(String s) { return s.strip().toUpperCase(Locale.ROOT); }
    private static QuoteError err(String s, Integer i) { return new QuoteError(s, i); }
    private static QuoteError check(Normalized n) {
        if (n.items().isEmpty()) return err("EMPTY_ORDER", null);
        if (n.items().size() > 50) return err("TOO_MANY_ITEMS", null);
        QuoteError rows = rowError(n.items());
        if (rows != null) return rows;
        return afterRows(n);
    }
    private static QuoteError afterRows(Normalized n) {
        QuoteError e = dup(n.items());
        return e == null ? opts(n) : e;
    }
    private static QuoteError rowError(List<RawItem> xs) {
        for (int i = 0; i < xs.size(); i++) {
            QuoteError e = itemError(xs.get(i), i);
            if (e != null) return e;
        }
        return null;
    }
    private static QuoteError itemError(RawItem x, int i) {
        if (!sko(x.sku())) return err("BAD_SKU", i);
        if (!qo(x.qty())) return err("BAD_QTY", i);
        return po(x.price()) ? null : err("BAD_PRICE", i);
    }
    private static boolean sko(String s) { return skuok(s); }
    private static boolean skuok(String s) { return SKU.matcher(s).matches(); }
    private static boolean qo(int q) { return qtyok(q); }
    private static boolean qtyok(int q) { return q >= 1 && q <= 1000; }
    private static boolean po(String p) { return priceok(p); }
    private static boolean priceok(String p) { return PRICE.matcher(p).matches() && cents(p) > 0; }
    private static long cents(String s) {
        String[] p = s.split("\\.", -1);
        return Long.parseLong(p[0]) * 100 + (p.length == 1 ? 0 :
                Long.parseLong((p[1] + "00").substring(0, 2)));
    }
    private static QuoteError dup(List<RawItem> xs) {
        Map<String, long[]> seen = new HashMap<>();
        for (int i = 0; i < xs.size(); i++) {
            RawItem x = xs.get(i);
            QuoteError e = duplicateAt(seen, x, i);
            if (e != null) return e;
        }
        return null;
    }
    private static QuoteError duplicateAt(Map<String, long[]> seen, RawItem x, int i) {
        long[] old = seen.get(x.sku());
        if (old == null) return remember(seen, x);
        return samePrice(old, x, i);
    }
    private static QuoteError remember(Map<String, long[]> seen, RawItem x) {
        seen.put(x.sku(), new long[]{x.qty(), cents(x.price())});
        return null;
    }
    private static QuoteError samePrice(long[] old, RawItem x, int i) {
        if (old[1] != cents(x.price())) return err("PRICE_CONFLICT", i);
        old[0] += x.qty();
        return old[0] > 1000 ? err("BAD_QTY", i) : null;
    }
    private static QuoteError opts(Normalized n) {
        QuoteError e = te(n.tier());
        if (e != null) return e;
        e = ce(n.coupon());
        if (e != null) return e;
        return re(n.region());
    }
    private static QuoteError te(String t) {
        return Set.of("basic", "silver", "gold").contains(t) ? null : err("BAD_TIER", null);
    }
    private static QuoteError ce(String c) {
        return c.isEmpty() || COUPON.matcher(c).matches() ? null : err("BAD_COUPON", null);
    }
    private static QuoteError re(String r) {
        return Set.of("EU", "US", "ASIA").contains(r) ? null : err("BAD_REGION", null);
    }
    private static TreeMap<String, long[]> merge(List<RawItem> xs) {
        TreeMap<String, long[]> out = new TreeMap<>();
        for (RawItem x : xs) mergeItem(out, x);
        return out;
    }
    private static void mergeItem(TreeMap<String, long[]> m, RawItem x) {
        long[] old = m.get(x.sku());
        if (old == null) m.put(x.sku(), new long[]{x.qty(), cents(x.price())});
        else old[0] += x.qty();
    }
    private static Amounts amounts(TreeMap<String, long[]> m, Normalized n) {
        long amount = sub(m);
        long td = rnd(amount, tb(n.tier()), 10000);
        long net = amount - td;
        long cd = cc(net, n.coupon());
        return new Amounts(amount, td, cd, net - cd);
    }
    private static long sub(TreeMap<String, long[]> m) {
        return sum(m.values());
    }
    private static long sum(Iterable<long[]> xs) {
        long n = 0;
        for (long[] x : xs) n += x[0] * x[1];
        return n;
    }
    private static long tb(String t) {
        return t.equals("gold") ? 1000 : t.equals("silver") ? 500 : 0;
    }
    private static long rnd(long n, long rate, long div) {
        return (n * rate * 2 + div) / (2 * div);
    }
    private static long cc(long n, String c) {
        if (c.startsWith("PCT")) return rnd(n, Long.parseLong(c.substring(3)), 100);
        if (c.startsWith("FIXED")) return Math.min(Long.parseLong(c.substring(5)) * 100, n);
        return 0;
    }
    private static List<Line> lines(TreeMap<String, long[]> m) {
        List<Line> out = new ArrayList<>();
        for (var e : m.entrySet()) out.add(line(e));
        return out;
    }
    private static Line line(Map.Entry<String, long[]> e) {
        long[] x = e.getValue();
        return new Line(e.getKey(), (int)x[0], x[1],
                x[0] * x[1]);
    }
    private static long rate(String r) {
        return r.equals("EU") ? 2000 : r.equals("US") ? 700 : 1000;
    }
    private static long base(String r) {
        return r.equals("EU") ? 800 : r.equals("US") ? 500 : 1200;
    }
    private static long limit(String r) {
        return r.equals("EU") ? 10000 : r.equals("US") ? 7500 : 15000;
    }
    private static long ship(Amounts a, Normalized n) {
        return n.coupon().equals("FREESHIP") || a.net() >= limit(n.region())
                ? 0 : base(n.region());
    }
    private static List<String> tags(Amounts a, long sh, long tx) {
        List<String> out = new ArrayList<>();
        tagTier(out, a.tier());
        tagCoupon(out, a.coupon());
        tagShip(out, sh);
        tagTax(out, tx);
        return out;
    }
    private static void tagTier(List<String> out, long n) {
        if (n > 0) out.add("tier");
    }
    private static void tagCoupon(List<String> out, long n) {
        if (n > 0) out.add("coupon");
    }
    private static void tagShip(List<String> out, long n) {
        if (n == 0) out.add("free-shipping");
    }
    private static void tagTax(List<String> out, long n) {
        if (n > 0) out.add("tax");
    }
    private static Quote done(TreeMap<String, long[]> m, Amounts a, Normalized n) {
        long sh = ship(a, n), tx = tax(a, n);
        return quote(lines(m), a, sh, tx);
    }
    private static Quote quote(List<Line> ls, Amounts a, long sh, long tx) {
        return new Quote(ls, a.subtotal(), a.tier(), a.coupon(), sh, tx,
                total(a.net(), sh, tx), tags(a, sh, tx));
    }
    private static long tax(Amounts a, Normalized n) {
        return rnd(a.net(), rate(n.region()), 10000);
    }
    private static long total(long n, long sh, long tx) {
        return n + sh + tx;
    }
}
