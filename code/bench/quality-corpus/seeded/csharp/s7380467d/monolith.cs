using System;
using System.Globalization;
using System.Collections.Generic;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string inputLine)
    {
        if (inputLine == null) throw new ArgumentException("Invalid input");
        var fields = inputLine.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");
        if (!decimal.TryParse(fields[0].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var weight)) throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var declaredValue)) throw new ArgumentException("Invalid value");
        var destination = fields[1].Trim().ToUpperInvariant();
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
        baseRate = decimal.Round(baseRate, 2, MidpointRounding.ToEven);
        zone = decimal.Round(zone, 2, MidpointRounding.ToEven);
        var fuel = decimal.Round((baseRate + zone) * .10m, 2, MidpointRounding.ToEven);
        var insurance = decimal.Round(Math.Min(declaredValue * .01m, 50m), 2, MidpointRounding.ToEven);
        var subtotal = decimal.Round(baseRate + zone + fuel + insurance, 2, MidpointRounding.ToEven);
        var tax = decimal.Round(subtotal * .08m, 2, MidpointRounding.ToEven);
        var total = decimal.Round(baseRate + zone + fuel + insurance + tax, 2, MidpointRounding.ToEven);
        return new Quote(baseRate, zone, fuel, insurance, tax, total);
    }

    public static string BuildReport(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var reports = new List<string>();
        foreach (var line in input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var quote = QuoteLine(line);
            var number = (reports.Count + 1).ToString(CultureInfo.InvariantCulture);
            reports.Add("Parcel " + number + ": BASE=" + quote.Base.ToString("0.00", CultureInfo.InvariantCulture) +
                " ZONE=" + quote.Zone.ToString("0.00", CultureInfo.InvariantCulture) +
                " FUEL=" + quote.Fuel.ToString("0.00", CultureInfo.InvariantCulture) +
                " INSURANCE=" + quote.Insurance.ToString("0.00", CultureInfo.InvariantCulture) +
                " TAX=" + quote.Tax.ToString("0.00", CultureInfo.InvariantCulture) +
                " TOTAL=" + quote.Total.ToString("0.00", CultureInfo.InvariantCulture));
        }
        return string.Join("\n", reports);
    }
}
