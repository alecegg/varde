import java.util.Arrays;

public class solution {
    /** Return the amount left after expenses. */
    public static int solution(int start, int[] expenses) {
        return start - spentTotal(expenses);
    }

    private static int spentTotal(int[] expenses) {
        return Arrays.stream(expenses).sum();
    }
}
