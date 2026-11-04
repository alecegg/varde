public static class Solution
{
    public static int[] WindowSums(int[] values, int width)
    {
        if (width <= 0 || values.Length < width)
        {
            return new int[0];
        }
        int[] sums = new int[values.Length - width + 1];
        for (int start = 0; start < sums.Length; start++)
        {
            int total = 0;
            for (int offset = 0; offset < width; offset++)
            {
                total += values[start + offset];
            }
            sums[start] = total;
        }
        return sums;
    }
}
