import java.util.HashMap;
import java.util.Map;

public class solution {
    private static final int STEP = 1;
    private static final int NONE = 0;
    private static final Map<Character, Integer> VALUE_TABLE = table();

    public static int toNumber(String text) {
        return total(values(text));
    }

    private static int total(int[] values) {
        int sum = NONE;
        for (int index = 0; index < values.length; index++) {
            sum += contribution(values, index);
        }
        return sum;
    }

    private static int contribution(int[] values, int index) {
        return direction(values[index], right(values, index + STEP)) * values[index];
    }

    private static int right(int[] values, int index) {
        return index < values.length ? values[index] : NONE;
    }

    private static int direction(int value, int next) {
        return next > value ? -STEP : STEP;
    }

    private static int[] values(String text) {
        int[] digits = new int[text.length()];
        for (int index = 0; index < text.length(); index++) {
            digits[index] = digitValue(text.charAt(index));
        }
        return digits;
    }

    private static int digitValue(char symbol) {
        return VALUE_TABLE.get(symbol);
    }

    private static Map<Character, Integer> table() {
        Map<Character, Integer> values = new HashMap<>();
        values.put('M', 1000);
        values.put('D', 500);
        values.put('C', 100);
        values.put('L', 50);
        values.put('X', 10);
        values.put('V', 5);
        values.put('I', 1);
        return values;
    }
}
