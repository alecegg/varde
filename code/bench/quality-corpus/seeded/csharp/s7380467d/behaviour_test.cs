using System;

public static class BehaviourTest
{
    private static int checks;

    public static int Main()
    {
        CheckQuote("1,LOCAL,100", 5m, 0m, .5m, 1m, .52m, 7.02m);
        CheckQuote("5,DOMESTIC,0", 8m, 4m, 1.2m, 0m, 1.06m, 14.26m);
        CheckQuote("5.01,international,200", 12m, 15m, 2.7m, 2m, 2.54m, 34.24m);
        CheckQuote("30,LOCAL,6000", 20m, 0m, 2m, 50m, 5.76m, 77.76m);
        var report = Original.BuildReport("\n1,LOCAL,100\n\n5,DOMESTIC,0\n");
        Assert(report == "Parcel 1: BASE=5.00 ZONE=0.00 FUEL=0.50 INSURANCE=1.00 TAX=0.52 TOTAL=7.02\nParcel 2: BASE=8.00 ZONE=4.00 FUEL=1.20 INSURANCE=0.00 TAX=1.06 TOTAL=14.26", "report formatting and blank lines");
        Assert(Original.BuildReport(" \n\r\n") == "", "empty report");
        Reject(""); Reject("1,LOCAL"); Reject("x,LOCAL,1"); Reject("1,LOCAL,x");
        Reject("0,LOCAL,0"); Reject("-1,LOCAL,0"); Reject("30.01,LOCAL,0");
        Reject("1,MOON,0"); Reject("1,LOCAL,-1"); Reject("1,LOCAL,0,extra");
        Reject("1,LOCAL,1.2.3");
        Assert(checks >= 15, "assertion count");
        return 0;
    }

    private static void CheckQuote(string input, decimal b, decimal z, decimal f, decimal i, decimal t, decimal total)
    {
        var q = Original.QuoteLine(input);
        Assert(q.Base == b, "base"); Assert(q.Zone == z, "zone"); Assert(q.Fuel == f, "fuel");
        Assert(q.Insurance == i, "insurance"); Assert(q.Tax == t, "tax"); Assert(q.Total == total, "total");
    }

    private static void Reject(string input)
    {
        var rejected = false;
        try { Original.QuoteLine(input); }
        catch (ArgumentException) { rejected = true; }
        Assert(rejected, "invalid input rejected: " + input);
    }

    private static void Assert(bool value, string label)
    {
        checks++;
        if (!value) throw new Exception("Check failed: " + label);
    }
}
