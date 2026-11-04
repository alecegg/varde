using System;
using System.Globalization;
using System.Collections.Generic;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string text)
    {
        if (text == null) throw new ArgumentException("Invalid input");
        var parts = text.Split(',');
        if (parts.Length != 3) throw new ArgumentException("Invalid input");
        if (!decimal.TryParse(parts[0].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var kilograms)) throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(parts[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var insuredAmount)) throw new ArgumentException("Invalid value");
        var region = parts[1].Trim().ToUpperInvariant();
        if (kilograms <= 0 || kilograms > 30 || insuredAmount < 0) throw new ArgumentException("Out of range");
        var charge = kilograms <= 1 ? 5m : kilograms <= 5 ? 8m : kilograms <= 10 ? 12m : 20m;
        var extra = region == "LOCAL" ? 0m : region == "DOMESTIC" ? 4m : region == "INTERNATIONAL" ? 15m : -1m;
        if (extra < 0) throw new ArgumentException("Invalid destination");
        charge = decimal.Round(charge, 2, MidpointRounding.ToEven);
        extra = decimal.Round(extra, 2, MidpointRounding.ToEven);
        var energy = decimal.Round((charge + extra) * .10m, 2, MidpointRounding.ToEven);
        var coverage = decimal.Round(Math.Min(insuredAmount * .01m, 50m), 2, MidpointRounding.ToEven);
        var taxable = decimal.Round(charge + extra + energy + coverage, 2, MidpointRounding.ToEven);
        var levy = decimal.Round(taxable * .08m, 2, MidpointRounding.ToEven);
        var due = decimal.Round(charge + extra + energy + coverage + levy, 2, MidpointRounding.ToEven);
        return new Quote(charge, extra, energy, coverage, levy, due);
    }

    public static string BuildReport(string text)
    {
        if (text == null) throw new ArgumentException("Invalid input");
        var result = new List<string>();
        foreach (var row in text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (string.IsNullOrWhiteSpace(row)) continue;
            var amount = QuoteLine(row);
            var ordinal = (result.Count + 1).ToString(CultureInfo.InvariantCulture);
            result.Add("Parcel " + ordinal + ": BASE=" + amount.Base.ToString("0.00", CultureInfo.InvariantCulture) +
                " ZONE=" + amount.Zone.ToString("0.00", CultureInfo.InvariantCulture) +
                " FUEL=" + amount.Fuel.ToString("0.00", CultureInfo.InvariantCulture) +
                " INSURANCE=" + amount.Insurance.ToString("0.00", CultureInfo.InvariantCulture) +
                " TAX=" + amount.Tax.ToString("0.00", CultureInfo.InvariantCulture) +
                " TOTAL=" + amount.Total.ToString("0.00", CultureInfo.InvariantCulture));
        }
        return string.Join("\n", result);
    }
}
