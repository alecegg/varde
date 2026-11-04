public class solution {
    public record Amount(int gratuity, int total) {}

    /** Return the tip and the total for a meal bill. */
    public static Amount solution(int bill, int percent) {
        int gratuityAmount = bill * percent / 100;
        return new Amount(gratuityAmount, bill + gratuityAmount);
    }
}
