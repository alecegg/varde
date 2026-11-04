public class behaviour_test {
    public static void main(String[] args) {
        check(32, solution.solution(0));
        check(212, solution.solution(100));
        check(-40, solution.solution(-40));
    }

    private static void check(double expected, double actual) {
        if (expected != actual) {
            throw new AssertionError("expected " + expected + " but got " + actual);
        }
    }
}
