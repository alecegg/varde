using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string s)
    {
        if (s == null) throw new ArgumentException("Invalid input");
        var fields = s.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");

        var weightText = fields[0].Trim();
        var destination = fields[1].Trim().ToUpperInvariant();
        var valueText = fields[2].Trim();
        if (!decimal.TryParse(weightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var weight))
            throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(valueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var value))
            throw new ArgumentException("Invalid value");
        if (weight <= 0 || weight > 30 || value < 0) throw new ArgumentException("Out of range");

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

        baseRate = decimal.Round(baseRate, 2, MidpointRounding.ToEven);
        zone = decimal.Round(zone, 2, MidpointRounding.ToEven);
        var fuel = decimal.Round((baseRate + zone) * .10m, 2, MidpointRounding.ToEven);
        var insurance = decimal.Round(Math.Min(value * .01m, 50m), 2, MidpointRounding.ToEven);
        var subtotal = decimal.Round(baseRate + zone + fuel + insurance, 2, MidpointRounding.ToEven);
        var tax = decimal.Round(subtotal * .08m, 2, MidpointRounding.ToEven);
        var total = decimal.Round(baseRate + zone + fuel + insurance + tax, 2, MidpointRounding.ToEven);
        return new Quote(baseRate, zone, fuel, insurance, tax, total);
    }

    public static string BuildReport(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var lines = input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var output = new List<string>();
        var parcel = 0;
        foreach (var line in lines)
        {
            if (line.Trim().Length == 0) continue;
            var quote = QuoteLine(line);
            parcel++;
            output.Add("Parcel " + parcel.ToString(CultureInfo.InvariantCulture) + ": BASE=" + quote.Base.ToString("0.00", CultureInfo.InvariantCulture)
                + " ZONE=" + quote.Zone.ToString("0.00", CultureInfo.InvariantCulture)
                + " FUEL=" + quote.Fuel.ToString("0.00", CultureInfo.InvariantCulture)
                + " INSURANCE=" + quote.Insurance.ToString("0.00", CultureInfo.InvariantCulture)
                + " TAX=" + quote.Tax.ToString("0.00", CultureInfo.InvariantCulture)
                + " TOTAL=" + quote.Total.ToString("0.00", CultureInfo.InvariantCulture));
        }
        return string.Join("\n", output);
    }
}
