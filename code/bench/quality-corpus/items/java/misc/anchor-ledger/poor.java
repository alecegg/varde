public class solution {
    /** Return the account balance after applying signed ledger entries. */
    public static int solution(int opening, int[] entries) {
        int b = opening;
        int i = 0;
        while (i < entries.length) {
            int e = entries[i];
            if (e < 0) {
                if (e == -3) {
                    b = b - 3;
                } else {
                    b = b + e;
                }
            } else {
                b = b + e;
            }
            i = i + 1;
        }
        return b;
    }
}
