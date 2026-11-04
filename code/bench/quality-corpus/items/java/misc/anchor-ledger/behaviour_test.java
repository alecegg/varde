public class behaviour_test {
    public static void main(String[] args) {
        check(12, solution.solution(10, new int[] {5, -3}));
        check(0, solution.solution(0, new int[] {}));
        check(50, solution.solution(100, new int[] {-20, -30}));
    }

    private static void check(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError("expected " + expected + " but got " + actual);
        }
    }
}
