(int Bill, int Percent, int WantGratuity, int WantTotal)[] cases =
[
    (Bill: 20, Percent: 10, WantGratuity: 2, WantTotal: 22),
    (Bill: 45, Percent: 20, WantGratuity: 9, WantTotal: 54),
    (Bill: 0, Percent: 15, WantGratuity: 0, WantTotal: 0),
];

foreach ((int bill, int percent, int wantGratuity, int wantTotal) in cases)
{
    BillTotal got = Solution.Gratuity(bill, percent);
    if (got.Gratuity != wantGratuity || got.Total != wantTotal)
    {
        throw new System.InvalidOperationException(
            $"Gratuity({bill}, {percent}) = ({got.Gratuity}, {got.Total}), want ({wantGratuity}, {wantTotal})");
    }
}
