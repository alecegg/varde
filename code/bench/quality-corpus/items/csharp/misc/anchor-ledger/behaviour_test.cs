(int Opening, int[] Entries, int Want)[] cases =
[
    (Opening: 10, Entries: new int[] { 5, -3 }, Want: 12),
    (Opening: 0, Entries: new int[] { }, Want: 0),
    (Opening: 100, Entries: new int[] { -20, -30 }, Want: 50),
];

foreach ((int opening, int[] entries, int want) in cases)
{
    int got = Solution.Balance(opening, entries);
    if (got != want)
    {
        throw new System.InvalidOperationException($"Balance({opening}) = {got}, want {want}");
    }
}
