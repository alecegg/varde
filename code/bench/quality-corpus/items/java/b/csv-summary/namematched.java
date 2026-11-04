import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class solution {
    record SaleRow(String product, int quantity, BigDecimal price) {}

    record ProductTotal(String product, int quantity, BigDecimal revenue) {}

    record Grouping(Map<String, List<SaleRow>> byProduct) {}

    private static final BigDecimal ZERO = BigDecimal.ZERO;

    /** Summarize valid sales rows by product with quantity and revenue totals. */
    public static List<ProductTotal> solution(List<SaleRow> rows) {
        return summaryLines(orderedProducts(checkedRows(rows)), groupByProduct(rows));
    }

    private static List<ProductTotal> summaryLines(List<String> names, Grouping grouped) {
        return names.stream().map(name -> productTotal(name, grouped)).toList();
    }

    private static ProductTotal productTotal(String name, Grouping grouped) {
        return new ProductTotal(name, countIn(grouped, name), rounded(revenueOf(grouped, name)));
    }

    private static int countIn(Grouping grouped, String name) {
        return rowsFor(grouped, name).mapToInt(SaleRow::quantity).sum();
    }

    private static BigDecimal revenueOf(Grouping grouped, String name) {
        return rowsFor(grouped, name).map(row -> line(row)).reduce(ZERO, BigDecimal::add);
    }

    private static BigDecimal line(SaleRow row) {
        return row.price().multiply(BigDecimal.valueOf(row.quantity()));
    }

    private static BigDecimal rounded(BigDecimal amount) {
        return amount.setScale(2, RoundingMode.HALF_UP);
    }

    private static Stream<SaleRow> rowsFor(Grouping grouped, String name) {
        return grouped.byProduct().get(name).stream();
    }

    private static List<String> orderedProducts(List<SaleRow> rows) {
        return distinctNames(rows);
    }

    private static List<String> distinctNames(List<SaleRow> rows) {
        return rows.stream().map(SaleRow::product).distinct().sorted().toList();
    }

    private static List<SaleRow> checkedRows(List<SaleRow> rows) {
        return everyRowAccepted(rows) ? rows : rejectedRows();
    }

    private static boolean everyRowAccepted(List<SaleRow> rows) {
        return rows.stream().allMatch(row -> rowAccepted(row));
    }

    private static List<SaleRow> rejectedRows() {
        throw new IllegalArgumentException("invalid_row");
    }

    private static boolean rowAccepted(SaleRow row) {
        return productNameValid(row) && quantityValid(row) && priceValid(row);
    }

    private static boolean productNameValid(SaleRow row) {
        return !row.product().isEmpty() && row.product().chars().allMatch(code -> code < 128);
    }

    private static boolean quantityValid(SaleRow row) {
        return row.quantity() >= 1;
    }

    private static boolean priceValid(SaleRow row) {
        return row.price().signum() >= 0;
    }

    private static Grouping groupByProduct(List<SaleRow> rows) {
        return new Grouping(rows.stream().collect(Collectors.groupingBy(SaleRow::product)));
    }
}
