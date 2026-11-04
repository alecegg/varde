using System.Globalization;

public static class Original
{
    public static string CreateReceipt(string line)
    {
        if (line == null) throw new FormatException("Input is required.");
        var input = line.Trim();
        if (input.Length == 0) throw new FormatException("Input is required.");
        var fields = input.Split(',');
        if (fields.Length != 3) throw new FormatException("Expected three fields.");

        var vehicleClass = fields[0].Trim().ToLowerInvariant();
        if (vehicleClass != "car" && vehicleClass != "motorcycle" && vehicleClass != "van")
            throw new FormatException("Unknown vehicle class.");
        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var hours))
            throw new FormatException("Hours must be an integer.");
        if (hours < 1 || hours > 168) throw new FormatException("Hours are outside the allowed range.");

        var validation = fields[2].Trim().ToLowerInvariant();
        bool validated;
        if (validation == "true") validated = true;
        else if (validation == "false") validated = false;
        else throw new FormatException("Validation must be true or false.");

        var total = CalculateFee(vehicleClass, hours, validated);
        return "Vehicle: " + vehicleClass + "\nHours: " + hours.ToString(CultureInfo.InvariantCulture) +
               "\nValidated: " + validation + "\nTotal: $" + total.ToString("F2", CultureInfo.InvariantCulture);
    }

    public static string CreateReport(IEnumerable<string> lines)
    {
        if (lines == null) throw new ArgumentNullException(nameof(lines));
        var receipts = new List<string>();
        foreach (var line in lines)
        {
            if (line == null || line.Trim().Length == 0) continue;
            receipts.Add(CreateReceipt(line));
        }
        return string.Join("\n", receipts);
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        if (hours < 1 || hours > 168) throw new ArgumentOutOfRangeException(nameof(hours));

        var normalizedClass = vehicleClass == null ? "" : vehicleClass.Trim().ToLowerInvariant();
        decimal rate;
        if (normalizedClass == "car") rate = 5m;
        else if (normalizedClass == "motorcycle") rate = 3m;
        else if (normalizedClass == "van") rate = 8m;
        else throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));

        decimal total = 0m;
        var remainingHours = hours;
        while (remainingHours > 0)
        {
            var blockHours = Math.Min(24, remainingHours);
            decimal blockCharge;
            if (blockHours <= 2) blockCharge = blockHours * rate;
            else if (blockHours <= 5) blockCharge = 2m * rate + (blockHours - 2) * rate * 1.5m;
            else blockCharge = 2m * rate + 3m * rate * 1.5m + (blockHours - 5) * rate * 2m;

            var cap = rate * 24m;
            if (blockCharge > cap) blockCharge = cap;
            total += blockCharge;
            remainingHours -= blockHours;
        }

        if (validated) total *= 0.9m;
        total *= 1.08m;
        return Math.Round(total, 2, MidpointRounding.AwayFromZero);
    }
}
