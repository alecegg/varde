import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class solution {
    record SaleRow(String product, int quantity, BigDecimal price) {}

    record ProductTotal(String product, int quantity, BigDecimal revenue) {}

    /** Summarize valid sales rows by product with quantity and revenue totals. */
    public static List<ProductTotal> solution(List<SaleRow> rows) {
        for (SaleRow row : rows) {
            String product = row.product();
            if (product.isEmpty()) {
                throw new IllegalArgumentException("invalid_row");
            }
            if (!product.chars().allMatch(code -> code < 128)) {
                throw new IllegalArgumentException("invalid_row");
            }
            if (row.quantity() < 1) {
                throw new IllegalArgumentException("invalid_row");
            }
            BigDecimal price = row.price();
            if (price.signum() < 0) {
                throw new IllegalArgumentException("invalid_row");
            }
        }
        Map<String, List<SaleRow>> groups = new HashMap<>();
        for (SaleRow row : rows) {
            String product = row.product();
            List<SaleRow> held = groups.get(product);
            if (held == null) {
                List<SaleRow> fresh = new ArrayList<>();
                fresh.add(row);
                groups.put(product, fresh);
            } else {
                held.add(row);
            }
        }
        List<String> names = new ArrayList<>(groups.keySet());
        names.sort(null);
        Map<String, Integer> quantities = new HashMap<>();
        for (String name : names) {
            int running = 0;
            List<SaleRow> held = groups.get(name);
            for (SaleRow row : held) {
                int quantity = row.quantity();
                int updated = running + quantity;
                running = updated;
            }
            quantities.put(name, running);
        }
        Map<String, BigDecimal> revenues = new HashMap<>();
        for (String name : names) {
            BigDecimal running = BigDecimal.ZERO;
            List<SaleRow> held = groups.get(name);
            for (SaleRow row : held) {
                BigDecimal price = row.price();
                int quantity = row.quantity();
                BigDecimal line = price.multiply(BigDecimal.valueOf(quantity));
                running = running.add(line);
            }
            revenues.put(name, running);
        }
        Map<String, BigDecimal> roundedRevenues = new HashMap<>();
        for (String name : names) {
            BigDecimal exact = revenues.get(name);
            BigDecimal rounded = exact.setScale(2, RoundingMode.HALF_UP);
            roundedRevenues.put(name, rounded);
        }
        List<ProductTotal> summary = new ArrayList<>();
        for (String name : names) {
            int quantity = quantities.get(name);
            BigDecimal revenue = roundedRevenues.get(name);
            summary.add(new ProductTotal(name, quantity, revenue));
        }
        return summary;
    }
}
