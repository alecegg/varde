import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.TreeMap;

public class behaviour_test {
    private static final BigInteger TEN = BigInteger.TEN;

    public static void main(String[] args) {
        check(List.of(row("Tea", 2, "3")), List.of(total("Tea", 2, "6")));
        check(List.of(), List.of());
        check(List.of(row("Pen", 3, "1.2"), row("Book", 1, "8")),
                List.of(total("Book", 1, "8"), total("Pen", 3, "3.6")));
        check(List.of(row("Tea", 1, "2"), row("Tea", 4, "2.5")),
                List.of(total("Tea", 5, "12")));
        check(List.of(row("A", 1, "0")), List.of(total("A", 1, "0")));
        check(List.of(row("z", 2, "1.11"), row("a", 2, "1.11")),
                List.of(total("a", 2, "2.22"), total("z", 2, "2.22")));
        check(List.of(row("Mug", 2, "4.5"), row("Mug", 1, "4.5"), row("Bag", 1, "7")),
                List.of(total("Bag", 1, "7"), total("Mug", 3, "13.5")));
        check(List.of(row("x", 10, "0.05")), List.of(total("x", 10, "0.5")));
        check(List.of(row("same", 1, "1"), row("Same", 1, "2")),
                List.of(total("Same", 1, "2"), total("same", 1, "1")));
        check(List.of(row("K", 7, "2.35")), List.of(total("K", 7, "16.45")));
        check(List.of(row("Half", 1, "1.005")), List.of(total("Half", 1, "1.01")));
        check(List.of(row("Half", 1, "0.004"), row("Half", 1, "0.004")),
                List.of(total("Half", 2, "0.01")));
        check(List.of(row("Half", 1, "2.345")), List.of(total("Half", 1, "2.35")));
        check(List.of(row("Half", 1, "1.2345"), row("Half", 1, "0.0005")),
                List.of(total("Half", 2, "1.24")));
        check(List.of(row("Thirds", 3, "0.001")), List.of(total("Thirds", 3, "0")));
        check(List.of(row("Del\u007f", 1, "2")), List.of(total("Del\u007f", 1, "2")));
        check(List.of(row("Mi\u007fxed", 2, "1.5")), List.of(total("Mi\u007fxed", 2, "3")));
        reject(List.of(row("", 1, "2")));
        reject(List.of(row("caf\u00e9", 1, "2")));
        reject(List.of(row("Up\u0080", 1, "2")));
        reject(List.of(row("Up\u0081", 1, "2")));
        reject(List.of(row("Mi\u0080xed", 1, "2")));
        reject(List.of(row("Smile\ud83d\ude00", 1, "2")));
        reject(List.of(row("Tea", 0, "2")));
        reject(List.of(row("Tea", -3, "2")));
        reject(List.of(row("Tea", 1, "-0.01")));
        reject(List.of(row("Tea", 1, "2"), row("", 4, "1")));
        reject(List.of(row("Tea", 1, "2"), row("A\u0080", 1, "1")));
        large();
    }

    private static void check(List<solution.SaleRow> rows, List<solution.ProductTotal> expected) {
        List<solution.ProductTotal> actual = solution.solution(rows);
        if (actual.size() != expected.size()) {
            throw new AssertionError(actual.size() + " != " + expected.size());
        }
        for (int index = 0; index < expected.size(); index++) {
            solution.ProductTotal want = expected.get(index);
            solution.ProductTotal got = actual.get(index);
            if (!want.product().equals(got.product())) {
                throw new AssertionError(want.product() + " != " + got.product());
            }
            if (want.quantity() != got.quantity()) {
                throw new AssertionError(want.quantity() + " != " + got.quantity());
            }
            equal(want.revenue(), got.revenue());
        }
    }

    private static void reject(List<solution.SaleRow> rows) {
        try {
            solution.solution(rows);
        } catch (IllegalArgumentException error) {
            if ("invalid_row".equals(error.getMessage())) {
                return;
            }
            throw error;
        }
        throw new AssertionError("invalid row accepted");
    }

    private static void large() {
        Random generator = new Random(20261017);
        List<solution.SaleRow> rows = new ArrayList<>();
        for (int index = 0; index < 3000; index++) {
            int millis = generator.nextInt(2000000);
            BigDecimal price = BigDecimal.valueOf(millis, 3);
            rows.add(row("P" + generator.nextInt(60), generator.nextInt(99) + 1,
                    price.toPlainString()));
        }
        List<solution.ProductTotal> actual = solution.solution(rows);
        List<solution.ProductTotal> expected = reference(rows);
        if (actual.size() != expected.size()) {
            throw new AssertionError(actual.size() + " != " + expected.size());
        }
        for (int index = 0; index < expected.size(); index++) {
            if (!expected.get(index).product().equals(actual.get(index).product())) {
                throw new AssertionError("order differs at " + index);
            }
            if (expected.get(index).quantity() != actual.get(index).quantity()) {
                throw new AssertionError("quantity differs at " + index);
            }
            equal(expected.get(index).revenue(), actual.get(index).revenue());
        }
    }

    private static List<solution.ProductTotal> reference(List<solution.SaleRow> rows) {
        Map<String, Integer> quantities = new TreeMap<>();
        Map<String, BigInteger> scaled = new TreeMap<>();
        for (solution.SaleRow row : rows) {
            BigInteger millis = row.price().unscaledValue();
            BigInteger line = millis.multiply(BigInteger.valueOf(row.quantity()));
            BigInteger seen = scaled.getOrDefault(row.product(), BigInteger.ZERO);
            scaled.put(row.product(), seen.add(line));
            int counted = quantities.getOrDefault(row.product(), 0);
            quantities.put(row.product(), counted + row.quantity());
        }
        List<solution.ProductTotal> summary = new ArrayList<>();
        for (String product : quantities.keySet()) {
            BigInteger total = scaled.get(product);
            BigInteger cents = total.add(BigInteger.valueOf(5)).divide(TEN);
            summary.add(new solution.ProductTotal(product, quantities.get(product),
                    new BigDecimal(cents).scaleByPowerOfTen(-2)));
        }
        return summary;
    }

    private static solution.SaleRow row(String product, int quantity, String price) {
        return new solution.SaleRow(product, quantity, new BigDecimal(price));
    }

    private static solution.ProductTotal total(String product, int quantity, String revenue) {
        return new solution.ProductTotal(product, quantity, new BigDecimal(revenue));
    }

    private static void equal(BigDecimal expected, BigDecimal actual) {
        if (expected.compareTo(actual) != 0) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}
