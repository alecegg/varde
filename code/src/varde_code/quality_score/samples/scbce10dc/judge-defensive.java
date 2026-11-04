import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    // These constants define the order-level rates and shipping boundaries.
    private static final BigDecimal ZERO = new BigDecimal("0.00");
    private static final BigDecimal TEN_PERCENT = new BigDecimal("0.10");
    private static final BigDecimal TAX_RATE = new BigDecimal("0.0825");
    private static final BigDecimal FREE_SHIPPING_MINIMUM = new BigDecimal("100.00");
    private static final BigDecimal REDUCED_SHIPPING_MINIMUM = new BigDecimal("50.00");

    // This record-like holder keeps the validated inventory values together.
    private static final class Item {
        private final String name;
        private final BigDecimal unitPrice;
        private final int stock;
        private final String group;

        // This constructor stores fields already checked by the inventory parser.
        private Item(String name, BigDecimal unitPrice, int stock, String group) {
            this.name = name;
            this.unitPrice = unitPrice;
            this.stock = stock;
            this.group = group;
        }
    }

    // This helper preserves empty rows so malformed delimiters remain detectable.
    private static String[] rows(String value) {
        if (value == null) {
            return new String[0];
        }
        return value.split("\\R", -1);
    }

    // This helper normalizes monetary results to the required cent precision.
    private static BigDecimal cents(BigDecimal value) {
        if (value == null) {
            return null;
        }
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    // This helper accepts only positive-digit integer representations.
    private static boolean whole(String value) {
        if (!(value instanceof String) || value.isEmpty()) {
            return false;
        }
        return value.matches("[0-9]+");
    }

    // This public entry point reports whether calculation accepts both inputs.
    public static boolean validate(String inventory, String order) {
        if (!(inventory instanceof String) || !(order instanceof String)) {
            return false;
        }
        return calculate(inventory, order) != null;
    }

    // This public entry point returns formatted totals or the invalid marker.
    public static String process(String inventory, String order) {
        if (!(inventory instanceof String) || !(order instanceof String)) {
            return "INVALID";
        }
        BigDecimal[] values = calculate(inventory, order);
        if (values == null || values.length != 5) {
            return "INVALID";
        }
        return "Subtotal=" + money(values[0]) + "; Discount=" + money(values[1])
                + "; Tax=" + money(values[2]) + "; Shipping=" + money(values[3])
                + "; Total=" + money(values[4]);
    }

    // This public entry point returns the same totals as labeled report lines.
    public static String report(String inventory, String order) {
        if (!(inventory instanceof String) || !(order instanceof String)) {
            return "INVALID";
        }
        BigDecimal[] values = calculate(inventory, order);
        if (values == null || values.length != 5) {
            return "INVALID";
        }
        return "Subtotal: " + money(values[0]) + "\nDiscount: " + money(values[1])
                + "\nTax: " + money(values[2]) + "\nShipping: " + money(values[3])
                + "\nTotal: " + money(values[4]);
    }

    // This helper renders a validated amount with exactly two decimal places.
    private static String money(BigDecimal value) {
        if (value == null) {
            return "0.00";
        }
        return value.setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    // This helper identifies rows that contain no non-whitespace characters.
    private static boolean blank(String value) {
        if (value == null) {
            return true;
        }
        return value.trim().isEmpty();
    }

    // This helper trims values before parsing or comparing them.
    private static String clean(String value) {
        if (value == null) {
            return "";
        }
        return value.trim();
    }

    // This helper restricts prices to nonnegative decimal amounts with cents precision.
    private static boolean amount(String value) {
        if (!(value instanceof String) || value.isEmpty()) {
            return false;
        }
        return value.matches("[0-9]+(\\.[0-9]{1,2})?");
    }

    // This helper computes a percentage amount and rounds it to cents.
    private static BigDecimal rate(BigDecimal value, String percent) {
        if (value == null || percent == null || percent.isEmpty()) {
            return null;
        }
        BigDecimal rate;
        try {
            rate = new BigDecimal(percent);
        } catch (NumberFormatException exception) {
            return null;
        }
        if (rate.signum() < 0) {
            return null;
        }
        return cents(value.multiply(rate));
    }

    // This method validates rows and computes all monetary values in one pass.
    private static BigDecimal[] calculate(String inventory, String order) {
        if (!(inventory instanceof String) || !(order instanceof String)) {
            return null;
        }

        // This map holds each unique, fully validated inventory item.
        Map<String, Item> items = new HashMap<>();
        for (String raw : rows(inventory)) {
            if (raw == null) {
                return null;
            }
            String line = clean(raw);
            if (blank(line)) {
                continue;
            }
            String[] fields = line.split("\\|", -1);
            if (fields.length != 5) {
                return null;
            }
            for (int index = 0; index < fields.length; index++) {
                if (fields[index] == null) {
                    return null;
                }
                fields[index] = clean(fields[index]);
            }
            if (fields[0].isEmpty() || fields[1].isEmpty() || !amount(fields[2])
                    || !whole(fields[3]) || fields[4].isEmpty()) {
                return null;
            }
            int stock;
            try {
                stock = Integer.parseInt(fields[3]);
            } catch (NumberFormatException exception) {
                return null;
            }
            if (stock <= 0 || items.containsKey(fields[0])) {
                return null;
            }
            BigDecimal price;
            try {
                price = new BigDecimal(fields[2]);
            } catch (NumberFormatException exception) {
                return null;
            }
            items.put(fields[0], new Item(fields[1], price, stock, fields[4]));
        }
        if (items.isEmpty()) {
            return null;
        }

        // This subtotal accumulates each validated order line after its group adjustment.
        BigDecimal subtotal = ZERO;
        for (String raw : rows(order)) {
            if (raw == null) {
                return null;
            }
            String line = clean(raw);
            if (blank(line)) {
                continue;
            }
            String[] fields = line.split("\\|", -1);
            if (fields.length != 2) {
                return null;
            }
            fields[0] = clean(fields[0]);
            fields[1] = clean(fields[1]);
            if (fields[0].isEmpty() || !whole(fields[1])) {
                return null;
            }
            int quantity;
            try {
                quantity = Integer.parseInt(fields[1]);
            } catch (NumberFormatException exception) {
                return null;
            }
            Item item = items.get(fields[0]);
            if (item == null || quantity <= 0 || quantity > item.stock) {
                return null;
            }
            BigDecimal lineAmount = cents(item.unitPrice.multiply(BigDecimal.valueOf(quantity)));
            if (lineAmount == null) {
                return null;
            }
            if ("A".equals(item.group)) {
                lineAmount = cents(lineAmount.multiply(new BigDecimal("0.95")));
            }
            if (lineAmount == null) {
                return null;
            }
            subtotal = subtotal.add(lineAmount);
        }
        if (subtotal.signum() < 0) {
            return null;
        }

        // This section applies the order discount, tax, shipping tier, and final total.
        subtotal = cents(subtotal);
        BigDecimal discount = rate(subtotal, TEN_PERCENT.toPlainString());
        if (discount == null) {
            return null;
        }
        BigDecimal afterDiscount = cents(subtotal.subtract(discount));
        BigDecimal tax = rate(afterDiscount, TAX_RATE.toPlainString());
        if (afterDiscount == null || tax == null) {
            return null;
        }
        BigDecimal shipping;
        if (afterDiscount.compareTo(FREE_SHIPPING_MINIMUM) >= 0) {
            shipping = ZERO;
        } else if (afterDiscount.compareTo(REDUCED_SHIPPING_MINIMUM) >= 0) {
            shipping = new BigDecimal("5.00");
        } else {
            shipping = new BigDecimal("8.00");
        }
        BigDecimal total = cents(afterDiscount.add(tax).add(shipping));
        if (total == null) {
            return null;
        }
        return new BigDecimal[] {subtotal, discount, tax, shipping, total};
    }
}
