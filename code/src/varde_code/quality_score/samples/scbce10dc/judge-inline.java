import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.Map;

public final class Original {
    private static final BigDecimal HUNDRED = new BigDecimal("100.00");
    private static final BigDecimal FIFTY = new BigDecimal("50.00");

    public static boolean validate(String inventory, String order) {
        return calculate(inventory, order) != null;
    }

    public static String process(String inventory, String order) {
        BigDecimal[] values = calculate(inventory, order);
        if (values == null) return "INVALID";
        return "Subtotal=" + values[0].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Discount=" + values[1].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Tax=" + values[2].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Shipping=" + values[3].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "; Total=" + values[4].setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    public static String report(String inventory, String order) {
        BigDecimal[] values = calculate(inventory, order);
        if (values == null) return "INVALID";
        return "Subtotal: " + values[0].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nDiscount: " + values[1].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nTax: " + values[2].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nShipping: " + values[3].setScale(2, RoundingMode.HALF_UP).toPlainString()
                + "\nTotal: " + values[4].setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    private static BigDecimal[] calculate(String inventory, String order) {
        if (inventory == null || order == null) return null;
        Map<String, Object[]> items = new HashMap<>();
        for (String raw : inventory.split("\\R", -1)) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\|", -1);
            if (fields.length != 5) return null;
            for (int i = 0; i < fields.length; i++) fields[i] = fields[i].trim();
            if (fields[0].isEmpty() || fields[1].isEmpty()
                    || !fields[2].matches("[0-9]+(\\.[0-9]{1,2})?")
                    || !fields[3].matches("[0-9]+") || fields[4].isEmpty()) return null;
            int stock;
            try {
                stock = Integer.parseInt(fields[3]);
            } catch (RuntimeException ex) {
                return null;
            }
            if (stock <= 0 || items.containsKey(fields[0])) return null;
            items.put(fields[0], new Object[] {new BigDecimal(fields[2]), stock, fields[4]});
        }
        if (items.isEmpty()) return null;

        BigDecimal subtotal = BigDecimal.ZERO;
        for (String raw : order.split("\\R", -1)) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            String[] fields = line.split("\\|", -1);
            if (fields.length != 2) return null;
            fields[0] = fields[0].trim();
            fields[1] = fields[1].trim();
            if (!fields[1].matches("[0-9]+")) return null;
            int quantity;
            try {
                quantity = Integer.parseInt(fields[1]);
            } catch (RuntimeException ex) {
                return null;
            }
            Object[] item = items.get(fields[0]);
            if (item == null || quantity <= 0 || quantity > (Integer) item[1]) return null;
            BigDecimal lineAmount = ((BigDecimal) item[0]).multiply(BigDecimal.valueOf(quantity))
                    .setScale(2, RoundingMode.HALF_UP);
            if ("A".equals(item[2])) {
                lineAmount = lineAmount.multiply(new BigDecimal("0.95")).setScale(2, RoundingMode.HALF_UP);
            }
            subtotal = subtotal.add(lineAmount);
        }

        subtotal = subtotal.setScale(2, RoundingMode.HALF_UP);
        BigDecimal discount = subtotal.multiply(new BigDecimal("0.10")).setScale(2, RoundingMode.HALF_UP);
        BigDecimal afterDiscount = subtotal.subtract(discount).setScale(2, RoundingMode.HALF_UP);
        BigDecimal tax = afterDiscount.multiply(new BigDecimal("0.0825")).setScale(2, RoundingMode.HALF_UP);
        BigDecimal shipping = afterDiscount.compareTo(HUNDRED) >= 0
                ? new BigDecimal("0.00")
                : afterDiscount.compareTo(FIFTY) >= 0 ? new BigDecimal("5.00") : new BigDecimal("8.00");
        BigDecimal total = afterDiscount.add(tax).add(shipping).setScale(2, RoundingMode.HALF_UP);
        return new BigDecimal[] {subtotal, discount, tax, shipping, total};
    }
}
