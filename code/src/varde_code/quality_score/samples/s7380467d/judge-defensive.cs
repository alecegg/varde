using System;
using System.Globalization;

public static class Original
{
    // This record keeps each calculated monetary component available to callers.
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    // This method validates one parcel line and returns its calculated quote.
    public static Quote QuoteLine(string s)
    {
        // Reject a missing line before attempting any string operations.
        if (s is not string line) throw new ArgumentException("Invalid input", nameof(s));

        // Require exactly three comma-separated fields for a parcel.
        var fields = line.Split(',');
        if (fields is not string[] || fields.Length != 3) throw new ArgumentException("Invalid input", nameof(s));

        // Trim the input fields and normalize the destination for comparison.
        var weightText = fields[0].Trim();
        var destination = fields[1].Trim().ToUpperInvariant();
        var valueText = fields[2].Trim();

        // Parse weight and declared value using invariant decimal syntax.
        if (!decimal.TryParse(weightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var weight))
            throw new ArgumentException("Invalid weight", nameof(s));
        if (!decimal.TryParse(valueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var value))
            throw new ArgumentException("Invalid value", nameof(s));

        // Enforce the supported parcel weight and nonnegative declared value limits.
        if (weight <= 0m || weight > 30m || value < 0m)
            throw new ArgumentException("Out of range", nameof(s));

        // Select the base price from the parcel's weight band.
        decimal baseRate;
        if (weight <= 1m) baseRate = 5m;
        else if (weight <= 5m) baseRate = 8m;
        else if (weight <= 10m) baseRate = 12m;
        else baseRate = 20m;

        // Select the surcharge associated with the normalized destination.
        decimal zoneRate;
        if (destination == "LOCAL") zoneRate = 0m;
        else if (destination == "DOMESTIC") zoneRate = 4m;
        else if (destination == "INTERNATIONAL") zoneRate = 15m;
        else throw new ArgumentException("Invalid destination", nameof(s));

        // Round every calculated component to cents using midpoint-to-even rules.
        baseRate = RoundMoney(baseRate);
        zoneRate = RoundMoney(zoneRate);
        var fuel = RoundMoney((baseRate + zoneRate) * 0.10m);
        var insurance = RoundMoney(Math.Min(value * 0.01m, 50m));
        var subtotal = RoundMoney(baseRate + zoneRate + fuel + insurance);
        var tax = RoundMoney(subtotal * 0.08m);
        var total = RoundMoney(baseRate + zoneRate + fuel + insurance + tax);

        // Return the complete quote with its individually rounded components.
        return new Quote(baseRate, zoneRate, fuel, insurance, tax, total);
    }

    // This method converts each nonblank input line into a numbered report row.
    public static string BuildReport(string input)
    {
        // Reject a missing report string before splitting it into lines.
        if (input is not string reportInput) throw new ArgumentException("Invalid input", nameof(input));

        // Prepare the report rows and count only lines that contain parcels.
        var output = new System.Collections.Generic.List<string>();
        var parcelNumber = 0;
        var lines = reportInput.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);

        // Skip blank lines and format each remaining parcel quote in order.
        foreach (var line in lines)
        {
            // Ignore whitespace-only lines without incrementing the parcel number.
            if (string.IsNullOrWhiteSpace(line)) continue;

            // Calculate the parcel quote and append its invariant-culture row.
            var quote = QuoteLine(line);
            parcelNumber++;
            output.Add("Parcel " + parcelNumber.ToString(CultureInfo.InvariantCulture) + ": " +
                "BASE=" + FormatMoney(quote.Base) + " " +
                "ZONE=" + FormatMoney(quote.Zone) + " " +
                "FUEL=" + FormatMoney(quote.Fuel) + " " +
                "INSURANCE=" + FormatMoney(quote.Insurance) + " " +
                "TAX=" + FormatMoney(quote.Tax) + " " +
                "TOTAL=" + FormatMoney(quote.Total));
        }

        // Join rows with the required newline separator and return an empty string for no rows.
        return string.Join("\n", output);
    }

    // This helper applies the required currency rounding rule.
    private static decimal RoundMoney(decimal amount)
    {
        // Round to two decimal places with midpoint values going to the even cent.
        return decimal.Round(amount, 2, MidpointRounding.ToEven);
    }

    // This helper formats a monetary value with invariant decimal separators.
    private static string FormatMoney(decimal amount)
    {
        // Emit exactly two fractional digits for every report component.
        return amount.ToString("0.00", CultureInfo.InvariantCulture);
    }
}
