void Check(int[] values, int width, string want)
{
    string got = string.Join(",", Solution.WindowSums(values, width));
    if (got != want)
    {
        throw new System.InvalidOperationException($"got {got}, want {want}");
    }
}

Check(new int[] { 1, 2, 3, 4, 5 }, 3, "6,9,12");
Check(new int[] { 4, 4, 4 }, 1, "4,4,4");
Check(new int[] { 10 }, 1, "10");
Check(new int[] { 1, 2 }, 5, "");
Check(new int[] { }, 1, "");
Check(new int[] { 2, 4, 6, 8 }, 2, "6,10,14");
Check(new int[] { 5, 5, 5, 5 }, 4, "20");
Check(new int[] { 0, 0, 0, 0 }, 2, "0,0,0");
Check(new int[] { 1, 0, 1, 0, 1 }, 2, "1,1,1,1");
Check(new int[] { 3, 1, 4, 1, 5 }, 1, "3,1,4,1,5");
Check(new int[] { 1, 2, 3 }, 0, "");
