import java.util.Arrays;

public class solution {
    /** Return the account balance after applying signed ledger entries. */
    public static int solution(int opening, int[] entries) {
        return opening + entriesTotal(entries);
    }

    private static int entriesTotal(int[] entries) {
        return Arrays.stream(entries).sum();
    }
}
