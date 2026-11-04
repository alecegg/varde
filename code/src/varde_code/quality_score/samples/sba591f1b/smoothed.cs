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

        var vehicleClass = NormalizeClass(fields[0]);
        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var hours))
            throw new FormatException("Hours must be an integer.");
        if (hours < 1 || hours > 168) throw new FormatException("Hours are outside the allowed range.");

        var validation = fields[2].Trim().ToLowerInvariant();
        bool validated;
        if (validation == "true") validated = true;
        else if (validation == "false") validated = false;
        else throw new FormatException("Validation must be true or false.");

        decimal rate;
        try { rate = GetRate(vehicleClass); }
        catch (ArgumentException) { throw new FormatException("Unknown vehicle class."); }

        var total = CalculateFee(rate, hours, validated);
        return $"Vehicle: {vehicleClass}\nHours: {hours.ToString(CultureInfo.InvariantCulture)}" +
            $"\nValidated: {validation}\nTotal: ${total.ToString("F2", CultureInfo.InvariantCulture)}";
    }

    public static string CreateReport(IEnumerable<string> lines)
    {
        if (lines == null) throw new ArgumentNullException(nameof(lines));
        var receipts = new List<string>();
        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            receipts.Add(CreateReceipt(line));
        }
        return string.Join("\n", receipts);
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        if (hours < 1 || hours > 168) throw new ArgumentOutOfRangeException(nameof(hours));
        return CalculateFee(GetRate(NormalizeClass(vehicleClass)), hours, validated);
    }

    private static decimal CalculateFee(decimal rate, int hours, bool validated)
    {
        decimal total = 0m;
        var remaining = hours;
        while (remaining > 0)
        {
            var blockHours = Math.Min(24, remaining);
            decimal blockTotal;
            if (blockHours <= 2) blockTotal = blockHours * rate;
            else if (blockHours <= 5) blockTotal = 2m * rate + (blockHours - 2) * rate * 1.5m;
            else blockTotal = 2m * rate + 3m * rate * 1.5m + (blockHours - 5) * rate * 2m;

            total += Math.Min(blockTotal, rate * 24m);
            remaining -= blockHours;
        }

        if (validated) total *= 0.9m;
        return Math.Round(total * 1.08m, 2, MidpointRounding.AwayFromZero);
    }

    private static string NormalizeClass(string vehicleClass) => (vehicleClass ?? "").Trim().ToLowerInvariant();

    private static decimal GetRate(string vehicleClass)
    {
        if (vehicleClass == "car") return 5m;
        if (vehicleClass == "motorcycle") return 3m;
        if (vehicleClass == "van") return 8m;
        throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
    }
}
