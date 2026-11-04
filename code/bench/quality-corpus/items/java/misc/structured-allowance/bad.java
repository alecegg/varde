public class solution {
    /** Return the amount left after expenses. */
    public static int solution(int start, int[] expenses) {
        if (expenses.length > 1) {
            int total = start;
            for (int expense : expenses) {
                total = total - expense;
            }
            return total;
        }
        int spentTotal = start;
        for (int expense : expenses) {
            spentTotal = spentTotal - expense;
        }
        return spentTotal;
    }
}
