import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

final class Original {
    private static final BigDecimal ORDER_DISCOUNT_RATE = new BigDecimal("0.10");
    private static final BigDecimal TAX_RATE = new BigDecimal("0.0825");
    private static final BigDecimal GROUP_A_RATE = new BigDecimal("0.95");
    private static final BigDecimal FREE_SHIPPING_MINIMUM = new BigDecimal("100.00");
    private static final BigDecimal REDUCED_SHIPPING_MINIMUM = new BigDecimal("50.00");
    private static final BigDecimal NO_SHIPPING = new BigDecimal("0.00");
    private static final class Item {
        final BigDecimal price;
        final int stock;
        final String group;
        Item(BigDecimal price, int stock, String group) { this.price = price; this.stock = stock; this.group = group; }
    }
    public static boolean validate(String inventory, String order) { return calculateOrder(inventory, order) != null; }
    public static String process(String inventory, String order) {
        BigDecimal[] t = calculateOrder(inventory, order);
        if (t == null) return "INVALID";
        return "Subtotal=" + t[0].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Discount=" + t[1].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Tax=" + t[2].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Shipping=" + t[3].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Total=" + t[4].setScale(2, RoundingMode.HALF_UP).toPlainString();
    }
    public static String report(String inventory, String order) {
        BigDecimal[] t = calculateOrder(inventory, order);
        if (t == null) return "INVALID";
        return "Subtotal: " + t[0].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nDiscount: " + t[1].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nTax: " + t[2].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nShipping: " + t[3].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nTotal: " + t[4].setScale(2, RoundingMode.HALF_UP).toPlainString();
    }
    private static BigDecimal[] calculateOrder(String stockRows, String purchaseRows) {
        if (stockRows == null || purchaseRows == null) return null;
        Map<String, Item> items = new HashMap<>();
        for (String row : stockRows.split("\\R", -1)) {
            if (row.trim().isEmpty()) continue;
            String[] f = row.split("\\|", -1);
            for (int i = 0; i < f.length; i++) f[i] = f[i].trim();
            if (f.length != 5 || f[0].isEmpty() || f[1].isEmpty() || !f[2].matches("[0-9]+(\\.[0-9]{1,2})?") || !f[3].matches("[0-9]+") || f[4].isEmpty()) return null;
            int stock;
            try { stock = Integer.parseInt(f[3]); } catch (NumberFormatException ex) { return null; }
            if (stock <= 0 || items.containsKey(f[0])) return null;
            items.put(f[0], new Item(new BigDecimal(f[2]), stock, f[4]));
        }
        if (items.isEmpty()) return null;
        BigDecimal preDiscountAmount = BigDecimal.ZERO;
        for (String row : purchaseRows.split("\\R", -1)) {
            if (row.trim().isEmpty()) continue;
            String[] f = row.split("\\|", -1);
            for (int i = 0; i < f.length; i++) f[i] = f[i].trim();
            if (f.length != 2 || !f[1].matches("[0-9]+")) return null;
            int units;
            try { units = Integer.parseInt(f[1]); } catch (NumberFormatException ex) { return null; }
            Item item = items.get(f[0]);
            if (item == null || units <= 0 || units > item.stock) return null;
            BigDecimal extendedPrice = item.price.multiply(BigDecimal.valueOf(units)).setScale(2, RoundingMode.HALF_UP);
            if ("A".equals(item.group)) extendedPrice = extendedPrice.multiply(GROUP_A_RATE).setScale(2, RoundingMode.HALF_UP);
            preDiscountAmount = preDiscountAmount.add(extendedPrice);
        }
        preDiscountAmount = preDiscountAmount.setScale(2, RoundingMode.HALF_UP);
        BigDecimal orderReduction = preDiscountAmount.multiply(ORDER_DISCOUNT_RATE).setScale(2, RoundingMode.HALF_UP);
        BigDecimal taxableAmount = preDiscountAmount.subtract(orderReduction).setScale(2, RoundingMode.HALF_UP);
        BigDecimal tax = taxableAmount.multiply(TAX_RATE).setScale(2, RoundingMode.HALF_UP);
        BigDecimal deliveryCharge;
        if (taxableAmount.compareTo(FREE_SHIPPING_MINIMUM) >= 0) deliveryCharge = NO_SHIPPING;
        else if (taxableAmount.compareTo(REDUCED_SHIPPING_MINIMUM) >= 0) deliveryCharge = new BigDecimal("5.00");
        else deliveryCharge = new BigDecimal("8.00");
        BigDecimal total = taxableAmount.add(tax).add(deliveryCharge).setScale(2, RoundingMode.HALF_UP);
        return new BigDecimal[] {preDiscountAmount, orderReduction, tax, deliveryCharge, total};
    }
}
