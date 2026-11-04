using System.Globalization;

public static class Original
{
    public static string CreateReceipt(string line)
    {
        var fields = ParseReceipt(line);
        var total = CalculateFee(fields.VehicleClass, fields.Hours, fields.Validated);
        return FormatReceipt(fields.VehicleClass, fields.Hours, fields.Validated, total);
    }

    public static string CreateReport(IEnumerable<string> lines)
    {
        if (lines == null) throw new ArgumentNullException(nameof(lines));
        return string.Join("\n", ReceiptLines(lines));
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        ValidateHours(hours);
        var baseRate = GetRate(NormalizeClass(vehicleClass));
        return FinalCharge(PriceBlocks(hours, baseRate), validated);
    }

    private static (string VehicleClass, int Hours, bool Validated) ParseReceipt(string line)
    {
        if (line == null) throw new FormatException("Input is required.");
        var fields = SplitFields(line);
        return (ParseClass(fields[0]), ParseHours(fields[1]), ParseValidation(fields[2]));
    }

    private static string[] SplitFields(string line)
    {
        var trimmed = line.Trim();
        if (trimmed.Length == 0) throw new FormatException("Input is required.");
        var fields = trimmed.Split(',');
        if (fields.Length != 3) throw new FormatException("Expected three fields.");
        return fields;
    }

    private static string ParseClass(string value)
    {
        var normalized = NormalizeClass(value);
        try { GetRate(normalized); }
        catch (ArgumentException) { throw new FormatException("Unknown vehicle class."); }
        return normalized;
    }

    private static string NormalizeClass(string value) => (value ?? "").Trim().ToLowerInvariant();

    private static int ParseHours(string value)
    {
        if (!int.TryParse(value.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var hours))
            throw new FormatException("Hours must be an integer.");
        if (hours < 1 || hours > 168) throw new FormatException("Hours are outside the allowed range.");
        return hours;
    }

    private static bool ParseValidation(string value)
    {
        var normalized = value.Trim().ToLowerInvariant();
        if (normalized == "true") return true;
        if (normalized == "false") return false;
        throw new FormatException("Validation must be true or false.");
    }

    private static decimal GetRate(string vehicleClass)
    {
        if (vehicleClass == "car") return 5m;
        if (vehicleClass == "motorcycle") return 3m;
        if (vehicleClass == "van") return 8m;
        throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
    }

    private static void ValidateHours(int hours)
    {
        if (hours < 1 || hours > 168) throw new ArgumentOutOfRangeException(nameof(hours));
    }

    private static decimal PriceBlocks(int hours, decimal rate)
    {
        var remaining = hours;
        var total = 0m;
        while (remaining > 0) total = AddNextBlock(ref remaining, total, rate);
        return total;
    }

    private static decimal AddNextBlock(ref int remaining, decimal total, decimal rate)
    {
        var blockHours = Math.Min(24, remaining);
        remaining -= blockHours;
        return total + PriceBlock(blockHours, rate);
    }

    private static decimal PriceBlock(int hours, decimal rate)
    {
        var charge = FirstTier(hours, rate) + SecondTier(hours, rate) + ThirdTier(hours, rate);
        return Math.Min(charge, rate * 24m);
    }

    private static decimal FirstTier(int hours, decimal rate) => Math.Min(hours, 2) * rate;

    private static decimal SecondTier(int hours, decimal rate) => Math.Max(0, Math.Min(hours - 2, 3)) * rate * 1.5m;

    private static decimal ThirdTier(int hours, decimal rate) => Math.Max(0, hours - 5) * rate * 2m;

    private static decimal FinalCharge(decimal charge, bool validated)
    {
        var discounted = ApplyDiscount(charge, validated);
        return RoundCurrency(ApplyTax(discounted));
    }

    private static decimal ApplyDiscount(decimal charge, bool validated) => validated ? charge * 0.9m : charge;

    private static decimal ApplyTax(decimal charge) => charge * 1.08m;

    private static decimal RoundCurrency(decimal charge) => Math.Round(charge, 2, MidpointRounding.AwayFromZero);

    private static IEnumerable<string> ReceiptLines(IEnumerable<string> lines)
    {
        foreach (var line in lines)
            if (!IsBlank(line)) yield return CreateReceipt(line);
    }

    private static bool IsBlank(string line) => line == null || line.Trim().Length == 0;

    private static string FormatReceipt(string vehicleClass, int hours, bool validated, decimal total)
    {
        return "Vehicle: " + vehicleClass + "\nHours: " + FormatHours(hours) +
            "\nValidated: " + FormatValidation(validated) + "\nTotal: $" + FormatMoney(total);
    }

    private static string FormatHours(int hours) => hours.ToString(CultureInfo.InvariantCulture);

    private static string FormatValidation(bool validated) => validated ? "true" : "false";

    private static string FormatMoney(decimal total) => total.ToString("F2", CultureInfo.InvariantCulture);
}
