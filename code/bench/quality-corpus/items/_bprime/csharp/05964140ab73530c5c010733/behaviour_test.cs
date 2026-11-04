void Check(string[] cells, int width, string want)
{
    string got = Solution.Row(cells, width);
    if (got != want)
    {
        throw new System.InvalidOperationException($"got '{got}', want '{want}'");
    }
}

Check(new string[] { "id", "name" }, 6, "id     | name  ");
Check(new string[] { "a" }, 3, "a  ");
Check(new string[] { }, 4, "");
Check(new string[] { "abc", "de" }, 3, "abc | de ");
Check(new string[] { "", "x" }, 2, "   | x ");
Check(new string[] { "left", "right" }, 5, "left  | right");
Check(new string[] { "1", "22", "333" }, 4, "1    | 22   | 333 ");
Check(new string[] { "total" }, 7, "total  ");
Check(new string[] { "ab", "cd", "ef" }, 2, "ab | cd | ef");
Check(new string[] { "x" }, 1, "x");
Check(new string[] { "longer", "x" }, 3, "longer | x  ");
Check(new string[] { "abcde" }, 2, "abcde");
