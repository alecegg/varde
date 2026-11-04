import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class solution {
    public static int[][] merge(int[][] ranges) {
        int[][] sorted = ranges.clone();
        Arrays.sort(sorted, (left, right) -> Integer.compare(left[0], right[0]));
        List<int[]> merged = new ArrayList<>();
        for (int[] range : sorted) {
            int[] last = merged.isEmpty() ? null : merged.get(merged.size() - 1);
            if (last != null && range[0] <= last[1]) {
                last[1] = Math.max(last[1], range[1]);
            } else {
                merged.add(new int[] {range[0], range[1]});
            }
        }
        return merged.toArray(new int[0][]);
    }
}
