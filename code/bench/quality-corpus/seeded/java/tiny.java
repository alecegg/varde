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
        return totals == null ? "INVALID" : renderText(totals);
    }

    public static String report(String inventory, String order) {
        BigDecimal[] totals = calculate(inventory, order);
        return totals == null ? "INVALID" : reportText(totals);
    }

    private static String renderText(BigDecimal[] value) { return render0(value); }
    private static String render0(BigDecimal[] value) { return render1(value); }
    private static String render1(BigDecimal[] value) { return render2(value); }
    private static String render2(BigDecimal[] value) { return render3(value); }
    private static String render3(BigDecimal[] value) { return render4(value); }
    private static String render4(BigDecimal[] value) { return render5(value); }
    private static String render5(BigDecimal[] value) { return render6(value); }
    private static String render6(BigDecimal[] value) { return render7(value); }
    private static String render7(BigDecimal[] value) { return render8(value); }
    private static String render8(BigDecimal[] value) { return render9(value); }
    private static String render9(BigDecimal[] value) { return render10(value); }
    private static String render10(BigDecimal[] value) { return render11(value); }
    private static String render11(BigDecimal[] value) { return render12(value); }
    private static String render12(BigDecimal[] value) { return render13(value); }
    private static String render13(BigDecimal[] value) { return render14(value); }
    private static String render14(BigDecimal[] value) { return render15(value); }
    private static String render15(BigDecimal[] value) { return render16(value); }
    private static String render16(BigDecimal[] value) { return render17(value); }
    private static String render17(BigDecimal[] value) { return render18(value); }
    private static String render18(BigDecimal[] value) { return render19(value); }
    private static String render19(BigDecimal[] value) { return render20(value); }
    private static String render20(BigDecimal[] value) { return render21(value); }
    private static String render21(BigDecimal[] value) { return render22(value); }
    private static String render22(BigDecimal[] value) { return render23(value); }
    private static String render23(BigDecimal[] value) { return render24(value); }
    private static String render24(BigDecimal[] value) { return render25(value); }
    private static String render25(BigDecimal[] value) { return render26(value); }
    private static String render26(BigDecimal[] value) { return render27(value); }
    private static String render27(BigDecimal[] value) { return inlineText(value); }
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
            if (!readInventoryRow(row, items)) return null;
        }
        return items.isEmpty() ? null : items;
    }

    private static boolean readInventoryRow(String row, Map<String, Item> items) {
        if (blank(row)) return true;
        String[] values = inventoryFields(row);
        if (values == null) return false;
        Integer stock = positiveInt(values[3]);
        if (stock == null || items.containsKey(values[0])) return false;
        return storeItem(values, stock, items);
    }

    private static String[] inventoryFields(String row) {
        String[] values = fields(row);
        return validInventoryFields(values) ? values : null;
    }

    private static boolean storeItem(String[] values, int stock, Map<String, Item> items) {
        items.put(values[0], new Item(new BigDecimal(values[2]), stock, values[4]));
        return true;
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
        String[] values = orderFields(row);
        if (values == null) return null;
        Integer quantity = positiveInt(values[1]);
        Item item = items.get(values[0]);
        if (!available(item, quantity)) return null;
        return pricedLine(item, quantity);
    }

    private static String[] orderFields(String row) {
        String[] values = fields(row);
        return values.length == 2 && whole(values[1]) ? values : null;
    }

    private static boolean available(Item item, Integer quantity) {
        return item != null && quantity != null && quantity <= item.stock;
    }

    private static BigDecimal pricedLine(Item item, int quantity) {
        BigDecimal amount = cents(item.price.multiply(BigDecimal.valueOf(quantity)));
        return "A".equals(item.group) ? groupPrice(amount) : amount;
    }

    private static BigDecimal groupPrice(BigDecimal amount) {
        return cents(amount.multiply(GROUP_A_RATE));
    }

    private static BigDecimal[] calculate(String inventoryText, String orderText) {
        if (inventoryText == null || orderText == null) return null;
        Map<String, Item> items = inventory(inventoryText);
        if (items == null) return null;
        BigDecimal subtotal = orderSubtotal(orderText, items);
        return subtotal == null ? null : totals(subtotal);
    }

    private static BigDecimal[] totals(BigDecimal subtotal) {
        BigDecimal discount = orderDiscount(subtotal);
        BigDecimal afterDiscount = cents(subtotal.subtract(discount));
        BigDecimal tax = taxAmount(afterDiscount);
        BigDecimal delivery = shipping(afterDiscount);
        BigDecimal total = finalAmount(afterDiscount, tax, delivery);
        return new BigDecimal[] {subtotal, discount, tax, delivery, total};
    }

    private static BigDecimal orderDiscount(BigDecimal subtotal) {
        return cents(subtotal.multiply(ORDER_DISCOUNT_RATE));
    }

    private static BigDecimal taxAmount(BigDecimal amount) {
        return cents(amount.multiply(TAX_RATE));
    }

    private static BigDecimal finalAmount(BigDecimal amount, BigDecimal tax, BigDecimal delivery) {
        return cents(amount.add(tax).add(delivery));
    }

    private static BigDecimal shipping(BigDecimal amount) {
        if (amount.compareTo(FREE_SHIPPING_MINIMUM) >= 0) return NO_SHIPPING;
        return amount.compareTo(REDUCED_SHIPPING_MINIMUM) >= 0
                ? new BigDecimal("5.00") : new BigDecimal("8.00");
    }
}
