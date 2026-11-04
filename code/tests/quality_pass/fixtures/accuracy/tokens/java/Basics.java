import java.util.List;

public final class Basics {
    private static final int MAX_RETRIES = 3;
    private static final String DEFAULT_NAME = "anonymous";
    private final List<String> names;

    public Basics(List<String> names) {
        this.names = names;
    }

    public int count() {
        int total = 0;
        for (String name : names) {
            if (name != null && !name.isEmpty()) {
                total += 1;
            }
        }
        return total;
    }

    public String render(int index) {
        if (index < 0 || index >= names.size()) {
            throw new IllegalArgumentException("index out of range: " + index);
        }
        return names.get(index).toUpperCase();
    }
}
