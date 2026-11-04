import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

public class Generics<T extends Comparable<T>> {
    private final List<T> items = new ArrayList<>();

    public void push(T item) {
        items.add(item);
    }

    public <R> List<R> map(Function<T, R> mapper) {
        List<R> mapped = new ArrayList<>(items.size());
        for (T item : items) {
            mapped.add(mapper.apply(item));
        }
        return mapped;
    }

    public T maximum() {
        T best = items.get(0);
        for (T item : items) {
            if (item.compareTo(best) > 0) {
                best = item;
            }
        }
        return best;
    }

    public static <N extends Number> double average(List<N> values) {
        double sum = 0.0;
        for (N value : values) {
            sum += value.doubleValue();
        }
        return values.isEmpty() ? 0.0 : sum / values.size();
    }
}
