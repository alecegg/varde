import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

public class solution {
    record SaleRow(String product, int quantity, BigDecimal price) {}

    record ProductTotal(String product, int quantity, BigDecimal revenue) {}

    record Totals(Map<String, Integer> counts, Map<String, BigDecimal> money) {}

    /** Summarize valid sales rows by product with quantity and revenue totals. */
    public static List<ProductTotal> solution(List<SaleRow> rows) {
        validated(rows);
        return report(new Totals(tallies(rows), revenues(rows)));
    }

    private static void validated(List<SaleRow> rows) {
        for (SaleRow row : rows) {
            boolean named = !row.product().isEmpty()
                    && row.product().chars().allMatch(code -> code < 128);
            if (!named || row.quantity() < 1 || row.price().signum() < 0) {
                throw new IllegalArgumentException("invalid_row");
            }
        }
    }

    private static Map<String, Integer> tallies(List<SaleRow> rows) {
        Map<String, Integer> counts = new TreeMap<>();
        for (SaleRow row : rows) {
            counts.merge(row.product(), row.quantity(), Integer::sum);
        }
        return counts;
    }

    private static Map<String, BigDecimal> revenues(List<SaleRow> rows) {
        Map<String, BigDecimal> money = new TreeMap<>();
        for (SaleRow row : rows) {
            BigDecimal line = row.price().multiply(BigDecimal.valueOf(row.quantity()));
            money.merge(row.product(), line, BigDecimal::add);
        }
        return money;
    }

    private static List<ProductTotal> report(Totals totals) {
        List<ProductTotal> summary = new ArrayList<>();
        for (String name : totals.counts().keySet()) {
            BigDecimal revenue = totals.money().get(name).setScale(2, RoundingMode.HALF_UP);
            summary.add(new ProductTotal(name, totals.counts().get(name), revenue));
        }
        return summary;
    }
}
