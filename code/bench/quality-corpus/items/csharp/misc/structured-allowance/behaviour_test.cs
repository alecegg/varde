(int Start, int[] Expenses, int Want)[] cases =
[
    (Start: 100, Expenses: new int[] { 10, 20 }, Want: 70),
    (Start: 50, Expenses: new int[] { }, Want: 50),
    (Start: 20, Expenses: new int[] { 5, 5, 2 }, Want: 8),
];

foreach ((int start, int[] expenses, int want) in cases)
{
    int got = Solution.Remaining(start, expenses);
    if (got != want)
    {
        throw new System.InvalidOperationException($"Remaining({start}, {expenses.Length}) = {got}, want {want}");
    }
}
