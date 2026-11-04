import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class solution {
    private static final int START = 0;
    private static final int END = 1;

    public static int[][] merge(int[][] ranges) {
        return toArrays(gather(sortKeys(ranges)));
    }

    private static int[][] sortKeys(int[][] ranges) {
        int[][] sorted = copyOf(ranges);
        Arrays.sort(sorted, solution::byStart);
        return sorted;
    }

    private static int[][] copyOf(int[][] ranges) {
        int[][] copy = new int[ranges.length][];
        for (int index = 0; index < ranges.length; index++) {
            copy[index] = pair(ranges[index][START], ranges[index][END]);
        }
        return copy;
    }

    private static int byStart(int[] left, int[] right) {
        return Integer.compare(left[START], right[START]);
    }

    private static List<int[]> gather(int[][] sorted) {
        List<int[]> merged = new ArrayList<>();
        for (int[] range : sorted) {
            absorb(merged, range);
        }
        return merged;
    }

    private static void absorb(List<int[]> merged, int[] range) {
        if (overlaps(merged, range)) {
            extend(last(merged), range[END]);
        } else {
            merged.add(pair(range[START], range[END]));
        }
    }

    private static boolean overlaps(List<int[]> merged, int[] range) {
        return !merged.isEmpty() && range[START] <= last(merged)[END];
    }

    private static int[] last(List<int[]> merged) {
        return merged.get(merged.size() - 1);
    }

    private static void extend(int[] target, int end) {
        target[END] = Math.max(target[END], end);
    }

    private static int[] pair(int start, int end) {
        return new int[] {start, end};
    }

    private static int[][] toArrays(List<int[]> merged) {
        return merged.toArray(new int[0][]);
    }
}
