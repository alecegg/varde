using static Harness;

Case("aggregates by key", () =>
    Equal("north: 2 rows, total 12.25\nsouth: 1 rows, total 5.50\nTOTAL: 3 rows, total 17.75",
        Report.Render("region,amount\nnorth,10\nsouth,5.5\nnorth,2.25\n", "region", "amount")));

Case("sorts by total then key", () =>
{
    var lines = Report.Render("k,v\nb,5\na,5\nc,7\n", "k", "v").Split('\n');
    Equal("c,a,b", string.Join(",", lines.Take(3).Select(l => l.Split(':')[0])));
});

Case("quoted field with comma", () =>
    Equal(true, Report.Render("name,v\n\"Smith, Jo\",4\n", "name", "v").StartsWith("Smith, Jo: 1 rows, total 4.00")));

Case("blank lines are ignored", () =>
    Equal("a: 2 rows, total 3.00\nTOTAL: 2 rows, total 3.00", Report.Render("k,v\n\na,1\n\n\na,2\n\n", "k", "v")));

Case("missing column is an error", () =>
{
    Throws(() => Report.Render("k,v\na,1\n", "k", "amount"));
    Throws(() => Report.Render("k,v\na,1\n", "name", "v"));
});

Case("non-numeric value is an error", () => Throws(() => Report.Render("k,v\na,abc\n", "k", "v")));

Case("other columns and order are ignored", () =>
    Equal("x: 2 rows, total 7.00\nTOTAL: 2 rows, total 7.00",
        Report.Render("id,amount,team\n1,3,x\n2,4,x\n", "team", "amount")));

Case("header only has no data", () => Equal("No data", Report.Render("k,v\n", "k", "v")));

return Finish();
