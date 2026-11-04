using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string inputLine)
    {
        if (inputLine == null) throw new ArgumentException("Invalid input");
        var fields = inputLine.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");

        var weightText = fields[0].Trim();
        var destination = fields[1].Trim().ToUpperInvariant();
        var valueText = fields[2].Trim();
        if (!decimal.TryParse(weightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var weight))
            throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(valueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var declaredValue))
            throw new ArgumentException("Invalid value");
        if (weight <= 0 || weight > 30 || declaredValue < 0) throw new ArgumentException("Out of range");

        decimal baseRate;
        if (weight <= 1) baseRate = 5m;
        else if (weight <= 5) baseRate = 8m;
        else if (weight <= 10) baseRate = 12m;
        else baseRate = 20m;

        decimal zone;
        if (destination == "LOCAL") zone = 0m;
        else if (destination == "DOMESTIC") zone = 4m;
        else if (destination == "INTERNATIONAL") zone = 15m;
        else throw new ArgumentException("Invalid destination");

        baseRate = RoundMoney(baseRate);
        zone = RoundMoney(zone);
        var fuel = RoundMoney((baseRate + zone) * 0.10m);
        var insurance = RoundMoney(Math.Min(declaredValue * 0.01m, 50m));
        var subtotal = RoundMoney(baseRate + zone + fuel + insurance);
        var tax = RoundMoney(subtotal * 0.08m);
        var total = RoundMoney(baseRate + zone + fuel + insurance + tax);
        return new Quote(baseRate, zone, fuel, insurance, tax, total);
    }

    public static string BuildReport(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var lines = input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var reportLines = new List<string>();
        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var quote = QuoteLine(line);
            var number = reportLines.Count + 1;
            reportLines.Add("Parcel " + number.ToString(CultureInfo.InvariantCulture) + ": " +
                FormatComponent("BASE", quote.Base) + " " +
                FormatComponent("ZONE", quote.Zone) + " " +
                FormatComponent("FUEL", quote.Fuel) + " " +
                FormatComponent("INSURANCE", quote.Insurance) + " " +
                FormatComponent("TAX", quote.Tax) + " " +
                FormatComponent("TOTAL", quote.Total));
        }
        return string.Join("\n", reportLines);
    }

    private static decimal RoundMoney(decimal amount) => decimal.Round(amount, 2, MidpointRounding.ToEven);

    private static string FormatComponent(string name, decimal amount) =>
        name + "=" + amount.ToString("0.00", CultureInfo.InvariantCulture);
}
