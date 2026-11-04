import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class solution {
    record SaleRow(String product, int quantity, BigDecimal price) {}

    record ProductTotal(String product, int quantity, BigDecimal revenue) {}

    record Grouping(Map<String, List<SaleRow>> byProduct) {}

    /** Summarize valid sales rows by product with quantity and revenue totals. */
    public static List<ProductTotal> solution(List<SaleRow> rows) {
        List<SaleRow> accepted = acceptedRows(rows);
        return renderLines(productNames(accepted), groupingOf(accepted));
    }

    private static List<ProductTotal> renderLines(List<String> names, Grouping groups) {
        List<ProductTotal> totals = new ArrayList<>();
        for (String name : names) {
            totals.add(totalForProduct(name, groups));
        }
        return totals;
    }

    private static ProductTotal totalForProduct(String name, Grouping groups) {
        int quantity = quantityOf(groups, name);
        BigDecimal revenue = toMoney(revenueFor(groups, name));
        return new ProductTotal(name, quantity, revenue);
    }

    private static int quantityOf(Grouping groups, String name) {
        Stream<SaleRow> rows = rowsFor(groups, name);
        int total = rows.mapToInt(SaleRow::quantity).sum();
        return total;
    }

    private static BigDecimal revenueFor(Grouping groups, String name) {
        Stream<SaleRow> rows = rowsFor(groups, name);
        Stream<BigDecimal> charges = rows.map(row -> lineChargeFor(row));
        BigDecimal revenue = charges.reduce(BigDecimal.ZERO, BigDecimal::add);
        return revenue;
    }

    private static BigDecimal lineChargeFor(SaleRow row) {
        BigDecimal price = row.price();
        BigDecimal units = BigDecimal.valueOf(row.quantity());
        BigDecimal line = price.multiply(units);
        return line;
    }

    private static BigDecimal toMoney(BigDecimal amount) {
        int digits = 2;
        RoundingMode mode = RoundingMode.HALF_UP;
        BigDecimal rounded = amount.setScale(digits, mode);
        return rounded;
    }

    private static Stream<SaleRow> rowsFor(Grouping groups, String name) {
        Map<String, List<SaleRow>> index = groups.byProduct();
        List<SaleRow> held = index.get(name);
        return held.stream();
    }

    private static List<String> productNames(List<SaleRow> rows) {
        List<String> ordered = sortedProducts(rows);
        return ordered;
    }

    private static List<String> sortedProducts(List<SaleRow> rows) {
        Stream<String> products = rows.stream().map(SaleRow::product);
        List<String> ordered = products.distinct().sorted().toList();
        return ordered;
    }

    private static List<SaleRow> acceptedRows(List<SaleRow> rows) {
        boolean usable = admitRows(rows);
        if (usable) {
            return rows;
        }
        return rejectRows();
    }

    private static boolean admitRows(List<SaleRow> rows) {
        boolean usable = rows.stream().allMatch(row -> rowUsable(row));
        return usable;
    }

    private static List<SaleRow> rejectRows() {
        String message = "invalid_row";
        IllegalArgumentException error = new IllegalArgumentException(message);
        throw error;
    }

    private static boolean rowUsable(SaleRow row) {
        boolean named = productUsable(row);
        boolean counted = quantityUsable(row);
        boolean priced = priceUsable(row);
        return named && counted && priced;
    }

    private static boolean productUsable(SaleRow row) {
        String product = row.product();
        boolean present = !product.isEmpty();
        boolean plain = product.chars().allMatch(code -> code < 128);
        boolean usable = present && plain;
        return usable;
    }

    private static boolean quantityUsable(SaleRow row) {
        int quantity = row.quantity();
        int minimum = 1;
        boolean positive = quantity >= minimum;
        return positive;
    }

    private static boolean priceUsable(SaleRow row) {
        BigDecimal price = row.price();
        boolean nonNegative = price.signum() >= 0;
        return nonNegative;
    }

    private static Grouping groupingOf(List<SaleRow> rows) {
        Map<String, List<SaleRow>> index = rows.stream()
                .collect(Collectors.groupingBy(SaleRow::product));
        return new Grouping(index);
    }
}
