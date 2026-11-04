import java.util.List;
import java.util.function.Function;

public class Generics {
    public <A, B> void pair(A a, B b) {
    }

    public <T extends Comparable<T>> T max(List<T> values, T fallback) {
        return fallback;
    }

    public void wildcard(List<? extends Number> values) {
    }

    public void nested(List<List<String>> matrix, int row) {
    }

    public <R> R apply(Function<String, R> mapper, String input) {
        return mapper.apply(input);
    }

    public void arrays(int[] values, String[] names) {
    }
}
