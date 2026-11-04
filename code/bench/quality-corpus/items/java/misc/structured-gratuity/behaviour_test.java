public class behaviour_test {
    public static void main(String[] args) {
        checkAmount(2, 22, 20, 10);
        checkAmount(9, 54, 45, 20);
        checkAmount(0, 0, 0, 15);
    }

    private static void checkAmount(int gratuity, int total, int bill, int percent) {
        solution.Amount actual = solution.solution(bill, percent);
        if (actual.gratuity() != gratuity || actual.total() != total) {
            throw new AssertionError(
                    "expected " + gratuity + ", " + total + " but got " + actual);
        }
    }
}
