public class behaviour_test {
    public static void main(String[] args) {
        check(70, solution.solution(100, new int[] {10, 20}));
        check(50, solution.solution(50, new int[] {}));
        check(8, solution.solution(20, new int[] {5, 5, 2}));
    }

    private static void check(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError("expected " + expected + " but got " + actual);
        }
    }
}
