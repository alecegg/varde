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
            "(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|"
                    + "[1-4][0-9]{2}|500)|FREESHIP)");

    /** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
    public static Object solution(Request request) {
        List<RawItem> items = new ArrayList<>();
        for (RawItem item : request.items()) {
            String normalizedSku = item.sku().strip().toUpperCase(Locale.ROOT);
            items.add(new RawItem(normalizedSku, item.qty(), item.price()));
        }
        String tier = request.tier().strip().toLowerCase(Locale.ROOT);
        String coupon = request.coupon().strip().toUpperCase(Locale.ROOT);
        String region = request.region().strip().toUpperCase(Locale.ROOT);
        Normalized normalized = new Normalized(items, tier, coupon, region);

        if (normalized.items().isEmpty()) {
            return new QuoteError("EMPTY_ORDER", null);
        }
        if (normalized.items().size() > 50) {
            return new QuoteError("TOO_MANY_ITEMS", null);
        }
        for (int index = 0; index < normalized.items().size(); index++) {
            RawItem item = normalized.items().get(index);
            boolean skuAccepted = SKU.matcher(item.sku()).matches();
            if (!skuAccepted) {
                return new QuoteError("BAD_SKU", index);
            }
            boolean quantityAccepted = item.qty() >= 1 && item.qty() <= 1000;
            if (!quantityAccepted) {
                return new QuoteError("BAD_QTY", index);
            }
            boolean priceTextAccepted = PRICE.matcher(item.price()).matches();
            if (!priceTextAccepted) {
                return new QuoteError("BAD_PRICE", index);
            }
            String[] priceParts = item.price().split("\\.", -1);
            long wholeCents = Long.parseLong(priceParts[0]) * 100;
            long fractionalCents;
            if (priceParts.length == 1) {
                fractionalCents = 0;
            } else {
                String fractionText = priceParts[1];
                if (fractionText.length() == 1) {
                    fractionalCents = Long.parseLong(fractionText) * 10;
                } else {
                    fractionalCents = Long.parseLong(fractionText);
                }
            }
            if (wholeCents + fractionalCents == 0) {
                return new QuoteError("BAD_PRICE", index);
            }
        }

        Map<String, long[]> firstPrices = new HashMap<>();
        for (int index = 0; index < normalized.items().size(); index++) {
            RawItem item = normalized.items().get(index);
            String[] priceParts = item.price().split("\\.", -1);
            long wholeCents = Long.parseLong(priceParts[0]) * 100;
            long fractionalCents;
            if (priceParts.length == 1) {
                fractionalCents = 0;
            } else {
                String fractionText = priceParts[1];
                if (fractionText.length() == 1) {
                    fractionalCents = Long.parseLong(fractionText) * 10;
                } else {
                    fractionalCents = Long.parseLong(fractionText);
                }
            }
            long unitCents = wholeCents + fractionalCents;
            long[] previous = firstPrices.get(item.sku());
            if (previous == null) {
                firstPrices.put(item.sku(), new long[]{item.qty(), unitCents});
                continue;
            }
            if (previous[1] != unitCents) {
                return new QuoteError("PRICE_CONFLICT", index);
            }
            long combinedQuantity = previous[0] + item.qty();
            if (combinedQuantity > 1000) {
                return new QuoteError("BAD_QTY", index);
            }
            previous[0] = combinedQuantity;
        }

        if (!Set.of("basic", "silver", "gold").contains(normalized.tier())) {
            return new QuoteError("BAD_TIER", null);
        }
        if (!normalized.coupon().isEmpty()
                && !COUPON.matcher(normalized.coupon()).matches()) {
            return new QuoteError("BAD_COUPON", null);
        }
        if (!Set.of("EU", "US", "ASIA").contains(normalized.region())) {
            return new QuoteError("BAD_REGION", null);
        }

        TreeMap<String, long[]> sortedItems = new TreeMap<>();
        for (RawItem item : normalized.items()) {
            String[] priceParts = item.price().split("\\.", -1);
            long wholeCents = Long.parseLong(priceParts[0]) * 100;
            long fractionalCents;
            if (priceParts.length == 1) {
                fractionalCents = 0;
            } else {
                String fractionText = priceParts[1];
                if (fractionText.length() == 1) {
                    fractionalCents = Long.parseLong(fractionText) * 10;
                } else {
                    fractionalCents = Long.parseLong(fractionText);
                }
            }
            long unitCents = wholeCents + fractionalCents;
            long[] previous = sortedItems.get(item.sku());
            if (previous == null) {
                sortedItems.put(item.sku(), new long[]{item.qty(), unitCents});
            } else {
                previous[0] += item.qty();
            }
        }

        List<Line> lines = new ArrayList<>();
        long subtotal = 0;
        for (Map.Entry<String, long[]> entry : sortedItems.entrySet()) {
            long quantity = entry.getValue()[0];
            long unitCents = entry.getValue()[1];
            long lineCents = quantity * unitCents;
            lines.add(new Line(entry.getKey(), (int) quantity, unitCents, lineCents));
            subtotal += lineCents;
        }

        long tierBasisPoints;
        if (normalized.tier().equals("silver")) {
            tierBasisPoints = 500;
        } else if (normalized.tier().equals("gold")) {
            tierBasisPoints = 1000;
        } else {
            tierBasisPoints = 0;
        }
        long tierDiscount = (subtotal * tierBasisPoints * 2 + 10000) / 20000;
        long afterTier = subtotal - tierDiscount;
        long couponDiscount;
        if (normalized.coupon().startsWith("PCT")) {
            long percent = Long.parseLong(normalized.coupon().substring(3));
            couponDiscount = (afterTier * percent * 2 + 100) / 200;
        } else if (normalized.coupon().startsWith("FIXED")) {
            long requestedCents = Long.parseLong(normalized.coupon().substring(5)) * 100;
            if (requestedCents < afterTier) {
                couponDiscount = requestedCents;
            } else {
                couponDiscount = afterTier;
            }
        } else {
            couponDiscount = 0;
        }
        Amounts amounts = new Amounts(subtotal, tierDiscount, couponDiscount,
                afterTier - couponDiscount);

        long taxBasisPoints;
        long baseShipping;
        long freeShippingThreshold;
        if (normalized.region().equals("EU")) {
            taxBasisPoints = 2000;
            baseShipping = 800;
            freeShippingThreshold = 10000;
        } else if (normalized.region().equals("US")) {
            taxBasisPoints = 700;
            baseShipping = 500;
            freeShippingThreshold = 7500;
        } else {
            taxBasisPoints = 1000;
            baseShipping = 1200;
            freeShippingThreshold = 15000;
        }
        boolean freeByCoupon = normalized.coupon().equals("FREESHIP");
        boolean freeByAmount = amounts.net() >= freeShippingThreshold;
        long shipping;
        if (freeByCoupon || freeByAmount) {
            shipping = 0;
        } else {
            shipping = baseShipping;
        }
        long taxableCents = amounts.net();
        long tax = (taxableCents * taxBasisPoints * 2 + 10000) / 20000;

        List<String> applied = new ArrayList<>();
        if (amounts.tier() > 0) {
            applied.add("tier");
        }
        if (amounts.coupon() > 0) {
            applied.add("coupon");
        }
        if (shipping == 0) {
            applied.add("free-shipping");
        }
        if (tax > 0) {
            applied.add("tax");
        }
        long total = amounts.net() + shipping + tax;
        long subtotalField = amounts.subtotal();
        long tierField = amounts.tier();
        long couponField = amounts.coupon();
        return new Quote(lines, subtotalField, tierField, couponField, shipping, tax, total,
                applied);
    }
}
