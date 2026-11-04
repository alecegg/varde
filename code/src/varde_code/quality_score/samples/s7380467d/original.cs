using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string s)
    {
        if (IsMissing(s)) throw new ArgumentException("Invalid input");
        var a = SplitFields(s);
        if (WrongShape(a)) throw new ArgumentException("Invalid input");
        var wtext = a[0].Trim();
        var d = a[1].Trim().ToUpperInvariant();
        var vtext = a[2].Trim();
        decimal w;
        decimal v;
        if (!ReadNumber(wtext, out w)) throw new ArgumentException("Invalid weight");
        if (!ReadNumber(vtext, out v)) throw new ArgumentException("Invalid value");
        if (OutsideLimits(w, v)) throw new ArgumentException("Out of range");
        decimal b;
        if (w <= 1) b = 5m;
        else if (w <= 5)
        {
            if (w > 1) b = 8m;
            else b = 5m;
        }
        else if (w <= 10) b = 12m;
        else b = 20m;
        decimal z;
        if (d == "LOCAL") z = 0m;
        else if (d == "DOMESTIC") z = 4m;
        else if (d == "INTERNATIONAL") z = 15m;
        else throw new ArgumentException("Invalid destination");
        b = R(b);
        z = R(z);
        var f = FuelPart(b, z);
        var i = CoverPart(v);
        var sub = R(b + z + f + i);
        var t = TaxPart(sub);
        var total = SumParts(b, z, f, i, t);
        return new Quote(b, z, f, i, t, total);
    }

    public static string BuildReport(string input)
    {
        if (IsMissing(input)) throw new ArgumentException("Invalid input");
        var lines = SplitLines(input);
        var output = new List<string>();
        var n = 0;
        foreach (var line in lines)
        {
            if (IsBlank(line)) continue;
            var q = QuoteLine(line);
            n++;
            output.Add(MakePrefix(n) + MakeBase(q.Base) + " " + MakeZone(q.Zone) + " " + MakeFuel(q.Fuel) + " " + MakeInsurance(q.Insurance) + " " + MakeTax(q.Tax) + " " + MakeTotal(q.Total));
        }
        return string.Join("\n", output);
    }

    private static decimal R(decimal x) => decimal.Round(x, 2, MidpointRounding.ToEven);
    private static string F(decimal x) => x.ToString("0.00", CultureInfo.InvariantCulture);

    private static bool IsMissing(string x) => x == null;

    private static string[] SplitFields(string x)
    {
        return x.Split(',');
    }

    private static bool WrongShape(string[] x)
    {
        return x.Length != 3;
    }

    private static bool ReadNumber(string x, out decimal y)
    {
        return decimal.TryParse(x, NumberStyles.Number, CultureInfo.InvariantCulture, out y);
    }

    private static bool OutsideLimits(decimal x, decimal y)
    {
        return x <= 0 || x > 30 || y < 0;
    }

    private static decimal FuelPart(decimal x, decimal y)
    {
        return R((x + y) * .10m);
    }

    private static decimal CoverPart(decimal x)
    {
        return R(Math.Min(x * .01m, 50m));
    }

    private static decimal TaxPart(decimal x)
    {
        return R(x * .08m);
    }

    private static decimal SumParts(decimal a, decimal b, decimal c, decimal d, decimal e)
    {
        return R(a + b + c + d + e);
    }

    private static string[] SplitLines(string x)
    {
        return x.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
    }

    private static bool IsBlank(string x)
    {
        return x.Trim().Length == 0;
    }

    private static string MakePrefix(int x)
    {
        return "Parcel " + x.ToString(CultureInfo.InvariantCulture) + ": ";
    }

    private static string MakeMoney(decimal x)
    {
        return F(x);
    }

    private static string MakeBase(decimal x)
    {
        return "BASE=" + MakeMoney(x);
    }

    private static string MakeZone(decimal x)
    {
        return "ZONE=" + MakeMoney(x);
    }

    private static string MakeFuel(decimal x)
    {
        return "FUEL=" + MakeMoney(x);
    }

    private static string MakeInsurance(decimal x)
    {
        return "INSURANCE=" + MakeMoney(x);
    }

    private static string MakeTax(decimal x)
    {
        return "TAX=" + MakeMoney(x);
    }

    private static string MakeTotal(decimal x)
    {
        return "TOTAL=" + MakeMoney(x);
    }
}
