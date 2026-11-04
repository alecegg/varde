import java.util.Arrays;

public class behaviour_test {
    public static void main(String[] args) {
        check("[[1, 6], [8, 10], [15, 18]]", solution.merge(new int[][] {{1, 3}, {2, 6}, {8, 10}, {15, 18}}));
        check("[[1, 5]]", solution.merge(new int[][] {{1, 4}, {4, 5}}));
        check("[[1, 2], [3, 4]]", solution.merge(new int[][] {{1, 2}, {3, 4}}));
        check("[]", solution.merge(new int[][] {}));
        check("[[5, 7]]", solution.merge(new int[][] {{5, 7}}));
        check("[[1, 9]]", solution.merge(new int[][] {{6, 8}, {1, 9}, {2, 3}}));
        check("[[1, 10]]", solution.merge(new int[][] {{1, 10}, {2, 3}, {4, 5}}));
        check("[[1, 2], [3, 5], [6, 7]]", solution.merge(new int[][] {{3, 5}, {1, 2}, {6, 7}}));
        check("[[1, 4]]", solution.merge(new int[][] {{1, 2}, {2, 3}, {3, 4}}));
        check("[[0, 0]]", solution.merge(new int[][] {{0, 0}}));
    }

    private static void check(String expected, int[][] actual) {
        String rendered = Arrays.deepToString(actual);
        if (!expected.equals(rendered)) {
            throw new AssertionError("expected " + expected + " but got " + rendered);
        }
    }
}
