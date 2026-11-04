import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    private Original() {}

    public static boolean validate(String inventory, String order) {
        return OrderCalculator.calculate(inventory, order) != null;
    }

    public static String process(String inventory, String order) {
        OrderSummary summary = OrderCalculator.calculate(inventory, order);
        return summary == null ? "INVALID" : summary.asInlineText();
    }

    public static String report(String inventory, String order) {
        OrderSummary summary = OrderCalculator.calculate(inventory, order);
        return summary == null ? "INVALID" : summary.asReportText();
    }
}

interface RowParser<T> {
    T parse(String row);
}

final class InventoryItem {
    final String sku;
    final String name;
    final BigDecimal unitPrice;
    final int stock;
    final String group;

    InventoryItem(String sku, String name, BigDecimal unitPrice, int stock, String group) {
        this.sku = sku;
        this.name = name;
        this.unitPrice = unitPrice;
        this.stock = stock;
        this.group = group;
    }
}

final class OrderLine {
    final String sku;
    final int quantity;

    OrderLine(String sku, int quantity) {
        this.sku = sku;
        this.quantity = quantity;
    }
}

final class InventoryParser implements RowParser<InventoryItem> {
    @Override public InventoryItem parse(String row) {
        String[] fields = fields(row, 5);
        if (fields == null || fields[0].isEmpty() || fields[1].isEmpty()
                || !fields[2].matches("[0-9]+(\\.[0-9]{1,2})?")
                || !fields[3].matches("[0-9]+") || fields[4].isEmpty()) return null;
        try {
            int stock = Integer.parseInt(fields[3]);
            if (stock <= 0) return null;
            return new InventoryItem(fields[0], fields[1], new BigDecimal(fields[2]), stock, fields[4]);
        } catch (RuntimeException ex) {
            return null;
        }
    }

    private static String[] fields(String row, int expected) {
        String[] values = row.split("\\|", -1);
        if (values.length != expected) return null;
        for (int i = 0; i < values.length; i++) values[i] = values[i].trim();
        return values;
    }
}

final class OrderParser implements RowParser<OrderLine> {
    @Override public OrderLine parse(String row) {
        String[] fields = row.split("\\|", -1);
        if (fields.length != 2) return null;
        String sku = fields[0].trim();
        String quantityText = fields[1].trim();
        if (!quantityText.matches("[0-9]+")) return null;
        try {
            int quantity = Integer.parseInt(quantityText);
            return sku.isEmpty() || quantity <= 0 ? null : new OrderLine(sku, quantity);
        } catch (RuntimeException ex) {
            return null;
        }
    }
}

interface GroupDiscount {
    BigDecimal apply(BigDecimal lineAmount);
}

final class DiscountPolicy {
    private static final GroupDiscount NONE = amount -> amount;
    private static final GroupDiscount GROUP_A = amount -> Money.round(amount.multiply(new BigDecimal("0.95")));

    BigDecimal apply(InventoryItem item, int quantity) {
        BigDecimal amount = Money.round(item.unitPrice.multiply(BigDecimal.valueOf(quantity)));
        return ("A".equals(item.group) ? GROUP_A : NONE).apply(amount);
    }
}

final class Money {
    private Money() {}
    static BigDecimal round(BigDecimal value) { return value.setScale(2, RoundingMode.HALF_UP); }
    static String format(BigDecimal value) { return round(value).toPlainString(); }
}

final class OrderSummary {
    final BigDecimal subtotal;
    final BigDecimal discount;
    final BigDecimal tax;
    final BigDecimal shipping;
    final BigDecimal total;

    OrderSummary(BigDecimal subtotal, BigDecimal discount, BigDecimal tax, BigDecimal shipping, BigDecimal total) {
        this.subtotal = subtotal;
        this.discount = discount;
        this.tax = tax;
        this.shipping = shipping;
        this.total = total;
    }

    String asInlineText() {
        return "Subtotal=" + Money.format(subtotal) + "; Discount=" + Money.format(discount)
                + "; Tax=" + Money.format(tax) + "; Shipping=" + Money.format(shipping)
                + "; Total=" + Money.format(total);
    }

    String asReportText() {
        return "Subtotal: " + Money.format(subtotal) + "\nDiscount: " + Money.format(discount)
                + "\nTax: " + Money.format(tax) + "\nShipping: " + Money.format(shipping)
                + "\nTotal: " + Money.format(total);
    }
}

final class OrderCalculator {
    private static final BigDecimal ORDER_DISCOUNT_RATE = new BigDecimal("0.10");
    private static final BigDecimal TAX_RATE = new BigDecimal("0.0825");
    private static final BigDecimal FIFTY = new BigDecimal("50.00");
    private static final BigDecimal HUNDRED = new BigDecimal("100.00");
    private final DiscountPolicy discounts = new DiscountPolicy();

    static OrderSummary calculate(String inventoryText, String orderText) {
        if (inventoryText == null || orderText == null) return null;
        Map<String, InventoryItem> inventory = parseInventory(inventoryText);
        if (inventory == null) return null;
        return new OrderCalculator().summarize(inventory, orderText);
    }

    private static Map<String, InventoryItem> parseInventory(String text) {
        Map<String, InventoryItem> inventory = new HashMap<>();
        InventoryParser parser = new InventoryParser();
        for (String raw : text.split("\\R", -1)) {
            String row = raw.trim();
            if (row.isEmpty()) continue;
            InventoryItem item = parser.parse(row);
            if (item == null || inventory.putIfAbsent(item.sku, item) != null) return null;
        }
        return inventory.isEmpty() ? null : inventory;
    }

    private OrderSummary summarize(Map<String, InventoryItem> inventory, String orderText) {
        BigDecimal subtotal = BigDecimal.ZERO;
        OrderParser parser = new OrderParser();
        for (String raw : orderText.split("\\R", -1)) {
            String row = raw.trim();
            if (row.isEmpty()) continue;
            OrderLine line = parser.parse(row);
            if (line == null) return null;
            InventoryItem item = inventory.get(line.sku);
            if (item == null || line.quantity > item.stock) return null;
            subtotal = subtotal.add(discounts.apply(item, line.quantity));
        }
        subtotal = Money.round(subtotal);
        BigDecimal discount = Money.round(subtotal.multiply(ORDER_DISCOUNT_RATE));
        BigDecimal afterDiscount = Money.round(subtotal.subtract(discount));
        BigDecimal tax = Money.round(afterDiscount.multiply(TAX_RATE));
        BigDecimal shipping = shippingFor(afterDiscount);
        BigDecimal total = Money.round(afterDiscount.add(tax).add(shipping));
        return new OrderSummary(subtotal, discount, tax, shipping, total);
    }

    private static BigDecimal shippingFor(BigDecimal amount) {
        if (amount.compareTo(HUNDRED) >= 0) return new BigDecimal("0.00");
        if (amount.compareTo(FIFTY) >= 0) return new BigDecimal("5.00");
        return new BigDecimal("8.00");
    }
}
