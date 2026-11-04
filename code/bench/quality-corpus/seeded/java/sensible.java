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

        Item(BigDecimal price, int stock, String group) {
            this.price = price;
            this.stock = stock;
            this.group = group;
        }
    }

    public static boolean validate(String inventory, String order) {
        return calculate(inventory, order) != null;
    }

    public static String process(String inventory, String order) {
        BigDecimal[] totals = calculate(inventory, order);
        return totals == null ? "INVALID" : inlineText(totals);
    }

    public static String report(String inventory, String order) {
        BigDecimal[] totals = calculate(inventory, order);
        return totals == null ? "INVALID" : reportText(totals);
    }

    private static String inlineText(BigDecimal[] totals) {
        return "Subtotal=" + money(totals[0]) + "; Discount=" + money(totals[1])
                + "; Tax=" + money(totals[2]) + "; Shipping=" + money(totals[3])
                + "; Total=" + money(totals[4]);
    }

    private static String reportText(BigDecimal[] totals) {
        return "Subtotal: " + money(totals[0]) + "\nDiscount: " + money(totals[1])
                + "\nTax: " + money(totals[2]) + "\nShipping: " + money(totals[3])
                + "\nTotal: " + money(totals[4]);
    }

    private static String money(BigDecimal value) {
        return cents(value).toPlainString();
    }

    private static BigDecimal cents(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    private static String[] rows(String text) {
        return text.split("\\R", -1);
    }

    private static String[] fields(String row) {
        String[] values = row.split("\\|", -1);
        for (int i = 0; i < values.length; i++) {
            values[i] = values[i].trim();
        }
        return values;
    }

    private static boolean blank(String value) {
        return value.trim().isEmpty();
    }

    private static boolean amount(String value) {
        return value.matches("[0-9]+(\\.[0-9]{1,2})?");
    }

    private static boolean whole(String value) {
        return value.matches("[0-9]+");
    }

    private static Integer positiveInt(String value) {
        try {
            int parsed = Integer.parseInt(value);
            return parsed > 0 ? parsed : null;
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static boolean validInventoryFields(String[] fields) {
        return fields.length == 5 && !fields[0].isEmpty() && !fields[1].isEmpty()
                && amount(fields[2]) && whole(fields[3]) && !fields[4].isEmpty();
    }

    private static Map<String, Item> inventory(String text) {
        Map<String, Item> items = new HashMap<>();
        for (String row : rows(text)) {
            if (blank(row)) continue;
            String[] values = fields(row);
            if (!validInventoryFields(values)) return null;
            Integer stock = positiveInt(values[3]);
            if (stock == null || items.containsKey(values[0])) return null;
            items.put(values[0], new Item(new BigDecimal(values[2]), stock, values[4]));
        }
        return items.isEmpty() ? null : items;
    }

    private static BigDecimal orderSubtotal(String text, Map<String, Item> items) {
        BigDecimal subtotal = BigDecimal.ZERO;
        for (String row : rows(text)) {
            if (blank(row)) continue;
            BigDecimal lineAmount = orderLine(row, items);
            if (lineAmount == null) return null;
            subtotal = subtotal.add(lineAmount);
        }
        return cents(subtotal);
    }

    private static BigDecimal orderLine(String row, Map<String, Item> items) {
        String[] values = fields(row);
        if (values.length != 2 || !whole(values[1])) return null;
        Integer quantity = positiveInt(values[1]);
        Item item = items.get(values[0]);
        if (item == null || quantity == null || quantity > item.stock) return null;

        BigDecimal lineAmount = cents(item.price.multiply(BigDecimal.valueOf(quantity)));
        return "A".equals(item.group) ? cents(lineAmount.multiply(GROUP_A_RATE)) : lineAmount;
    }

    private static BigDecimal[] calculate(String inventoryText, String orderText) {
        if (inventoryText == null || orderText == null) return null;
        Map<String, Item> items = inventory(inventoryText);
        if (items == null) return null;
        BigDecimal subtotal = orderSubtotal(orderText, items);
        return subtotal == null ? null : totals(subtotal);
    }

    private static BigDecimal[] totals(BigDecimal subtotal) {
        BigDecimal discount = cents(subtotal.multiply(ORDER_DISCOUNT_RATE));
        BigDecimal afterDiscount = cents(subtotal.subtract(discount));
        BigDecimal tax = cents(afterDiscount.multiply(TAX_RATE));
        BigDecimal shipping = shipping(afterDiscount);
        BigDecimal total = cents(afterDiscount.add(tax).add(shipping));
        return new BigDecimal[] {subtotal, discount, tax, shipping, total};
    }

    private static BigDecimal shipping(BigDecimal amount) {
        if (amount.compareTo(FREE_SHIPPING_MINIMUM) >= 0) return NO_SHIPPING;
        return amount.compareTo(REDUCED_SHIPPING_MINIMUM) >= 0
                ? new BigDecimal("5.00") : new BigDecimal("8.00");
    }
}
