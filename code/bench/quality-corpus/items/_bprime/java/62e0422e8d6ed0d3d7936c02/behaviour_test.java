public class behaviour_test {
    public static void main(String[] args) {
        check(1, solution.toNumber("I"));
        check(4, solution.toNumber("IV"));
        check(9, solution.toNumber("IX"));
        check(40, solution.toNumber("XL"));
        check(58, solution.toNumber("LVIII"));
        check(1994, solution.toNumber("MCMXCIV"));
        check(2024, solution.toNumber("MMXXIV"));
        check(444, solution.toNumber("CDXLIV"));
        check(3999, solution.toNumber("MMMCMXCIX"));
        check(0, solution.toNumber(""));
    }

    private static void check(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError("expected " + expected + " but got " + actual);
        }
    }
}
