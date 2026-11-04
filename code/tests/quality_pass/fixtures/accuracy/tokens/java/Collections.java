import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class Collections {
    private final Map<String, Integer> counts = new HashMap<>();

    public void add(String key) {
        counts.merge(key, 1, Integer::sum);
    }

    public List<String> top(int limit) {
        List<Map.Entry<String, Integer>> entries = new ArrayList<>(counts.entrySet());
        entries.sort((left, right) -> right.getValue() - left.getValue());
        List<String> result = new ArrayList<>();
        for (int index = 0; index < entries.size() && index < limit; index++) {
            result.add(entries.get(index).getKey());
        }
        return result;
    }

    public int total() {
        int sum = 0;
        for (int value : counts.values()) {
            sum += value;
        }
        return sum;
    }
}
