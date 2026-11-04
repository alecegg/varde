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
        return lines(names(required(rows)), grouped(rows));
    }

    private static List<ProductTotal> lines(List<String> names, Grouping grouped) {
        return names.stream().map(name -> totalFor(name, grouped)).toList();
    }

    private static ProductTotal totalFor(String name, Grouping grouped) {
        return new ProductTotal(name, qtyIn(grouped, name), rnd(revSum(grouped, name)));
    }

    private static int qtyIn(Grouping grouped, String name) {
        return rowsOf(grouped, name).mapToInt(SaleRow::quantity).sum();
    }

    private static BigDecimal revSum(Grouping grouped, String name) {
        return rowsOf(grouped, name).map(row -> lineOf(row)).reduce(ZERO, BigDecimal::add);
    }

    private static BigDecimal lineOf(SaleRow row) {
        return row.price().multiply(BigDecimal.valueOf(row.quantity()));
    }

    private static BigDecimal rnd(BigDecimal amount) {
        return amount.setScale(2, RoundingMode.HALF_UP);
    }

    private static Stream<SaleRow> rowsOf(Grouping grouped, String name) {
        return grouped.byProduct().get(name).stream();
    }

    private static List<String> names(List<SaleRow> rows) {
        return sortedNames(rows);
    }

    private static List<String> sortedNames(List<SaleRow> rows) {
        return rows.stream().map(SaleRow::product).distinct().sorted().toList();
    }

    private static List<SaleRow> required(List<SaleRow> rows) {
        return admitted(rows) ? rows : refused();
    }

    private static boolean admitted(List<SaleRow> rows) {
        return rows.stream().allMatch(row -> rowOk(row));
    }

    private static List<SaleRow> refused() {
        throw new IllegalArgumentException("invalid_row");
    }

    private static boolean rowOk(SaleRow row) {
        return nameOk(row) && quantityOk(row) && priceOk(row);
    }

    private static boolean nameOk(SaleRow row) {
        return !row.product().isEmpty() && row.product().chars().allMatch(code -> code < 128);
    }

    private static boolean quantityOk(SaleRow row) {
        return row.quantity() >= 1;
    }

    private static boolean priceOk(SaleRow row) {
        return row.price().signum() >= 0;
    }

    private static Grouping grouped(List<SaleRow> rows) {
        return new Grouping(rows.stream().collect(Collectors.groupingBy(SaleRow::product)));
    }
}
