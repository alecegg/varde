import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

public class solution {
    record SaleRow(String product, int quantity, BigDecimal price) {}

    record ProductTotal(String product, int quantity, BigDecimal revenue) {}

    /** Summarize valid sales rows by product with quantity and revenue totals. */
    public static List<ProductTotal> solution(List<SaleRow> rows) {
        for (SaleRow row : rows) {
            String product = row.product();
            boolean named = !product.isEmpty() && product.chars().allMatch(code -> code < 128);
            int minimum = 1;
            boolean counted = row.quantity() >= minimum;
            boolean priced = row.price().signum() >= 0;
            if (!named) {
                throw new IllegalArgumentException("invalid_row");
            }
            if (!counted) {
                throw new IllegalArgumentException("invalid_row");
            }
            if (!priced) {
                throw new IllegalArgumentException("invalid_row");
            }
        }
        Map<String, Integer> counts = new TreeMap<>();
        for (SaleRow row : rows) {
            String name = row.product();
            int quantity = row.quantity();
            int seen = counts.getOrDefault(name, 0);
            counts.put(name, seen + quantity);
        }
        Map<String, BigDecimal> money = new TreeMap<>();
        for (SaleRow row : rows) {
            String name = row.product();
            BigDecimal price = row.price();
            int units = row.quantity();
            BigDecimal line = price.multiply(BigDecimal.valueOf(units));
            BigDecimal seen = money.getOrDefault(name, BigDecimal.ZERO);
            BigDecimal updated = seen.add(line);
            money.put(name, updated);
        }
        List<ProductTotal> summary = new ArrayList<>();
        for (String name : counts.keySet()) {
            int quantity = counts.get(name);
            BigDecimal exact = money.get(name);
            RoundingMode mode = RoundingMode.HALF_UP;
            BigDecimal rounded = exact.setScale(2, mode);
            summary.add(new ProductTotal(name, quantity, rounded));
        }
        return summary;
    }
}
