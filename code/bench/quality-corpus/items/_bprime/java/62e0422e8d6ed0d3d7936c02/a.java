public class solution {
    private static final String SYMBOLS = "MDCLXVI";
    private static final int[] VALUES = {1000, 500, 100, 50, 10, 5, 1};

    public static int toNumber(String text) {
        int previous = 0;
        int total = 0;
        for (int index = text.length() - 1; index >= 0; index--) {
            int value = VALUES[SYMBOLS.indexOf(text.charAt(index))];
            if (value < previous) {
                total -= value;
            } else {
                total += value;
            }
            previous = value;
        }
        return total;
    }
}
