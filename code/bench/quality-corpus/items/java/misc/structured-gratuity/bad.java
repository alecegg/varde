public class solution {
    public record Amount(int gratuity, int total) {}

    /** Return the tip and the total for a meal bill. */
    public static Amount solution(int bill, int percent) {
        int x = g(bill, percent);
        int y = bill + x;
        return new Amount(x, y);
    }

    private static int g(int a, int b) {
        return a * b / 100;
    }
}
