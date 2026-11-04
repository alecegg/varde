import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    private static final BigDecimal ZERO = new BigDecimal("0.00");
    private static final class Item {
        final BigDecimal price;
        final int stock;
        final String group;
        Item(String price, int stock, String group) {
            this.price = new BigDecimal(price);
            this.stock = stock;
            this.group = group;
        }
    }
    public static boolean validate(String inventory, String order) {
        return calculate(inventory, order) != null;
    }
    public static String process(String inventory, String order) {
        BigDecimal[] values = calculate(inventory, order);
        return values == null ? "INVALID" : processText(values);
    }
    public static String report(String inventory, String order) {
        BigDecimal[] values = calculate(inventory, order);
        return values == null ? "INVALID" : reportText(values);
    }
    private static String processText(BigDecimal[] v) {
        return "Subtotal=" + money(v[0]) + "; Discount=" + money(v[1]) + "; Tax=" + money(v[2]) + "; Shipping=" + money(v[3]) + "; Total=" + money(v[4]);
    }
    private static String reportText(BigDecimal[] v) {
        return "Subtotal: " + money(v[0]) + "\nDiscount: " + money(v[1]) + "\nTax: " + money(v[2]) + "\nShipping: " + money(v[3]) + "\nTotal: " + money(v[4]);
    }
    private static String money(BigDecimal value) { return cents(value).toPlainString(); }
    private static BigDecimal cents(BigDecimal value) { return value.setScale(2, RoundingMode.HALF_UP); }
    private static String[] rows(String value) { return value.split("\\R", -1); }
    private static String[] fields(String row) { return trimmedFields(row.split("\\|", -1)); }
    private static String[] trimmedFields(String[] fields) {
        for (int i = 0; i < fields.length; i++) fields[i] = clean(fields[i]);
        return fields;
    }
    private static String clean(String value) { return value.trim(); }
    private static boolean blank(String value) { return value.trim().isEmpty(); }
    private static boolean amount(String value) { return value.matches("[0-9]+(\\.[0-9]{1,2})?"); }
    private static boolean whole(String value) { return value.matches("[0-9]+"); }
    private static boolean nonempty(String value) { return !value.isEmpty(); }
    private static boolean validInventoryFields(String[] f) {
        return f.length == 5 && nonempty(f[0]) && nonempty(f[1]) && amount(f[2]) && whole(f[3]) && nonempty(f[4]);
    }
    private static Integer positiveInt(String value) {
        try { int parsed = Integer.parseInt(value); return parsed > 0 ? parsed : null; }
        catch (RuntimeException ex) { return null; }
    }
    private static Map<String, Item> inventory(String text) {
        Map<String, Item> items = new HashMap<>();
        if (text == null || !addInventoryRows(text, items) || items.isEmpty()) return null;
        return items;
    }
    private static boolean addInventoryRows(String text, Map<String, Item> items) {
        for (String row : rows(text)) if (!addInventoryRow(row, items)) return false;
        return true;
    }
    private static boolean addInventoryRow(String raw, Map<String, Item> items) {
        if (blank(raw)) return true;
        String[] f = fields(raw);
        return validInventoryFields(f) && addItem(f, items);
    }
    private static boolean addItem(String[] f, Map<String, Item> items) {
        Integer stock = positiveInt(f[3]);
        if (stock == null || items.containsKey(f[0])) return false;
        items.put(f[0], new Item(f[2], stock, f[4]));
        return true;
    }
    private static BigDecimal orderSubtotal(String text, Map<String, Item> items) {
        if (text == null) return null;
        BigDecimal total = BigDecimal.ZERO;
        for (String row : rows(text)) {
            if (blank(row)) continue;
            BigDecimal amount = orderLine(row, items);
            if (amount == null) return null;
            total = total.add(amount);
        }
        return total.signum() < 0 ? null : cents(total);
    }
    private static BigDecimal orderLine(String raw, Map<String, Item> items) {
        String[] f = fields(raw);
        if (f.length != 2 || !whole(f[1])) return null;
        return priceLine(f[0], positiveInt(f[1]), items);
    }
    private static BigDecimal priceLine(String sku, Integer quantity, Map<String, Item> items) {
        Item item = items.get(sku);
        if (item == null || quantity == null || quantity > item.stock) return null;
        return discountedLine(item, quantity);
    }
    private static BigDecimal discountedLine(Item item, int quantity) {
        BigDecimal amount = cents(item.price.multiply(BigDecimal.valueOf(quantity)));
        return item.group.equals("A") ? cents(amount.multiply(new BigDecimal("0.95"))) : amount;
    }
    private static BigDecimal[] calculate(String inventoryText, String orderText) {
        Map<String, Item> items = inventory(inventoryText);
        if (items == null) return null;
        BigDecimal subtotal = orderSubtotal(orderText, items);
        return subtotal == null ? null : totals(subtotal);
    }
    private static BigDecimal[] totals(BigDecimal subtotal) {
        BigDecimal discount = rate(subtotal, "0.10");
        BigDecimal afterDiscount = cents(subtotal.subtract(discount));
        BigDecimal tax = rate(afterDiscount, "0.0825");
        BigDecimal shipping = shipping(afterDiscount);
        return new BigDecimal[] {subtotal, discount, tax, shipping, cents(afterDiscount.add(tax).add(shipping))};
    }
    private static BigDecimal rate(BigDecimal value, String rate) {
        return cents(value.multiply(new BigDecimal(rate)));
    }
    private static BigDecimal shipping(BigDecimal value) {
        if (value.compareTo(new BigDecimal("100.00")) >= 0) return ZERO;
        return value.compareTo(new BigDecimal("50.00")) >= 0 ? new BigDecimal("5.00") : new BigDecimal("8.00");
    }
}
