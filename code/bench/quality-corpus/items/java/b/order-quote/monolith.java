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

    /** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
    public static Object solution(Request request) {
        Pattern skuPattern = Pattern.compile("[A-Z0-9-]{3,12}");
        Pattern pricePattern = Pattern.compile("[0-9]{1,6}(\\.[0-9]{1,2})?");
        Pattern couponPattern = Pattern.compile(
                "(?:PCT(?:[1-9]|[1-4][0-9]|50)|FIXED(?:[1-9]|[1-9][0-9]|"
                        + "[1-4][0-9]{2}|500)|FREESHIP)");
        List<RawItem> normalizedItems = new ArrayList<>();
        for (RawItem raw : request.items()) {
            String normalizedSku = raw.sku().strip().toUpperCase(Locale.ROOT);
            normalizedItems.add(new RawItem(normalizedSku, raw.qty(), raw.price()));
        }
        String normalizedTier = request.tier().strip().toLowerCase(Locale.ROOT);
        String normalizedCoupon = request.coupon().strip().toUpperCase(Locale.ROOT);
        String normalizedRegion = request.region().strip().toUpperCase(Locale.ROOT);
        Normalized normalized = new Normalized(
                normalizedItems, normalizedTier, normalizedCoupon, normalizedRegion);
        if (normalized.items().isEmpty()) return new QuoteError("EMPTY_ORDER", null);
        if (normalized.items().size() > 50) return new QuoteError("TOO_MANY_ITEMS", null);
        for (int itemIndex = 0; itemIndex < normalized.items().size(); itemIndex++) {
            RawItem current = normalized.items().get(itemIndex);
            boolean validSku = skuPattern.matcher(current.sku()).matches();
            if (!validSku) return new QuoteError("BAD_SKU", itemIndex);
            boolean validQuantity = current.qty() >= 1 && current.qty() <= 1000;
            if (!validQuantity) return new QuoteError("BAD_QTY", itemIndex);
            boolean validPriceText = pricePattern.matcher(current.price()).matches();
            if (!validPriceText) return new QuoteError("BAD_PRICE", itemIndex);
            String[] priceParts = current.price().split("\\.", -1);
            long wholePart = Long.parseLong(priceParts[0]);
            long fractionalPart;
            if (priceParts.length == 1) {
                fractionalPart = 0;
            } else {
                String fractionText = priceParts[1];
                if (fractionText.length() == 1) {
                    fractionalPart = Long.parseLong(fractionText) * 10;
                } else {
                    fractionalPart = Long.parseLong(fractionText);
                }
            }
            long wholeCents = wholePart * 100;
            long parsedCents = wholeCents + fractionalPart;
            if (parsedCents == 0) return new QuoteError("BAD_PRICE", itemIndex);
        }
        Map<String, long[]> firstPricesAndQuantities = new HashMap<>();
        for (int itemIndex = 0; itemIndex < normalized.items().size(); itemIndex++) {
            RawItem current = normalized.items().get(itemIndex);
            String[] priceParts = current.price().split("\\.", -1);
            long wholePart = Long.parseLong(priceParts[0]);
            long fractionalPart;
            if (priceParts.length == 1) {
                fractionalPart = 0;
            } else {
                String fractionText = priceParts[1];
                if (fractionText.length() == 1) fractionalPart = Long.parseLong(fractionText) * 10;
                else fractionalPart = Long.parseLong(fractionText);
            }
            long wholeCents = wholePart * 100;
            long unitCents = wholeCents + fractionalPart;
            long[] first = firstPricesAndQuantities.get(current.sku());
            if (first == null) {
                long initialQuantity = current.qty();
                long initialPrice = unitCents;
                long[] firstOccurrence = new long[]{initialQuantity, initialPrice};
                firstPricesAndQuantities.put(current.sku(), firstOccurrence);
            } else if (first[1] != unitCents) {
                return new QuoteError("PRICE_CONFLICT", itemIndex);
            } else {
                long combinedQuantity = first[0] + current.qty();
                first[0] = combinedQuantity;
                if (combinedQuantity > 1000) {
                    return new QuoteError("BAD_QTY", itemIndex);
                }
            }
        }
        if (!Set.of("basic", "silver", "gold").contains(normalized.tier())) {
            return new QuoteError("BAD_TIER", null);
        }
        if (!normalized.coupon().isEmpty()
                && !couponPattern.matcher(normalized.coupon()).matches()) {
            return new QuoteError("BAD_COUPON", null);
        }
        if (!Set.of("EU", "US", "ASIA").contains(normalized.region())) {
            return new QuoteError("BAD_REGION", null);
        }
        TreeMap<String, long[]> sortedLines = new TreeMap<>();
        long subtotal = 0;
        for (RawItem current : normalized.items()) {
            String[] priceParts = current.price().split("\\.", -1);
            long wholePart = Long.parseLong(priceParts[0]);
            long unitCents = wholePart * 100;
            if (priceParts.length > 1) {
                String fractionText = priceParts[1];
                long fractionalPart;
                if (fractionText.length() == 1) fractionalPart = Long.parseLong(fractionText) * 10;
                else fractionalPart = Long.parseLong(fractionText);
                unitCents += fractionalPart;
            }
            long[] previous = sortedLines.get(current.sku());
            if (previous == null) {
                long firstQuantity = current.qty();
                long firstUnitPrice = unitCents;
                sortedLines.put(current.sku(), new long[]{firstQuantity, firstUnitPrice});
            } else {
                long nextQuantity = previous[0] + current.qty();
                previous[0] = nextQuantity;
            }
        }
        List<Line> lines = new ArrayList<>();
        for (Map.Entry<String, long[]> entry : sortedLines.entrySet()) {
            long[] values = entry.getValue();
            long lineCents = values[0] * values[1];
            subtotal += lineCents;
            lines.add(new Line(entry.getKey(), (int) values[0], values[1], lineCents));
        }
        long tierBasisPoints;
        if (normalized.tier().equals("basic")) {
            tierBasisPoints = 0;
        } else if (normalized.tier().equals("silver")) {
            tierBasisPoints = 500;
        } else {
            tierBasisPoints = 1000;
        }
        long tierProduct = subtotal * tierBasisPoints;
        long doubledTierProduct = tierProduct * 2;
        long roundedTierNumerator = doubledTierProduct + 10000;
        long tierDiscount = roundedTierNumerator / 20000;
        long afterTier = subtotal - tierDiscount;
        long couponDiscount = 0;
        if (normalized.coupon().startsWith("PCT")) {
            long percent = Long.parseLong(normalized.coupon().substring(3));
            long percentageProduct = afterTier * percent;
            long doubledPercentage = percentageProduct * 2;
            long roundedPercentage = doubledPercentage + 100;
            couponDiscount = roundedPercentage / 200;
        } else if (normalized.coupon().startsWith("FIXED")) {
            long fixedCents = Long.parseLong(normalized.coupon().substring(5)) * 100;
            if (fixedCents < afterTier) {
                couponDiscount = fixedCents;
            } else {
                couponDiscount = afterTier;
            }
        }
        long net = afterTier - couponDiscount;
        long taxBasisPoints;
        long shippingBase;
        long freeShippingThreshold;
        if (normalized.region().equals("EU")) {
            taxBasisPoints = 2000;
            shippingBase = 800;
            freeShippingThreshold = 10000;
        } else if (normalized.region().equals("US")) {
            taxBasisPoints = 700;
            shippingBase = 500;
            freeShippingThreshold = 7500;
        } else {
            taxBasisPoints = 1000;
            shippingBase = 1200;
            freeShippingThreshold = 15000;
        }
        boolean freeShipCoupon = normalized.coupon().equals("FREESHIP");
        boolean netMeetsThreshold = net >= freeShippingThreshold;
        long shipping;
        if (freeShipCoupon) {
            shipping = 0;
        } else if (netMeetsThreshold) {
            shipping = 0;
        } else {
            shipping = shippingBase;
        }
        long taxProduct = net * taxBasisPoints;
        long doubledTaxProduct = taxProduct * 2;
        long roundedTaxNumerator = doubledTaxProduct + 10000;
        long tax = roundedTaxNumerator / 20000;
        List<String> applied = new ArrayList<>();
        if (tierDiscount > 0) applied.add("tier");
        if (couponDiscount > 0) applied.add("coupon");
        if (shipping == 0) applied.add("free-shipping");
        if (tax > 0) applied.add("tax");
        long total = net + shipping + tax;
        return new Quote(lines, subtotal, tierDiscount, couponDiscount,
                shipping, tax, total, applied);
    }
}
