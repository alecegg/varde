using System.Globalization;

// This class exposes parking receipt, report, and fee operations.
public static class Original
{
    // This method validates one input line and formats its receipt.
    public static string CreateReceipt(string line)
    {
        // This guard rejects a missing line using the receipt parsing exception contract.
        if (line is null)
        {
            throw new FormatException("Input is required.");
        }

        // This guard rejects a line containing no usable text.
        var input = line.Trim();
        if (input.Length == 0)
        {
            throw new FormatException("Input is required.");
        }

        // This check ensures the line contains exactly the three required fields.
        var fields = input.Split(',');
        if (fields.Length != 3)
        {
            throw new FormatException("Expected three fields.");
        }

        // This normalization makes class and boolean parsing case-insensitive.
        var vehicleClass = fields[0].Trim().ToLowerInvariant();
        var hoursText = fields[1].Trim();
        var validationText = fields[2].Trim().ToLowerInvariant();

        // This check rejects text that cannot be parsed as an integer hour count.
        if (!int.TryParse(hoursText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var hours))
        {
            throw new FormatException("Hours must be an integer.");
        }

        // This guard enforces the supported parking duration.
        if (hours < 1 || hours > 168)
        {
            throw new FormatException("Hours are outside the allowed range.");
        }

        // This check accepts only the two defined validation values.
        bool validated;
        if (validationText == "true")
        {
            validated = true;
        }
        else if (validationText == "false")
        {
            validated = false;
        }
        else
        {
            throw new FormatException("Validation must be true or false.");
        }

        // This guard rejects unrecognized vehicle classes before pricing.
        if (!TryGetRate(vehicleClass, out _))
        {
            throw new FormatException("Unknown vehicle class.");
        }

        // This call computes the fee after all receipt fields have been validated.
        var total = CalculateFee(vehicleClass, hours, validated);

        // This formatting block emits normalized fields and a culture-independent amount.
        return "Vehicle: " + vehicleClass
            + "\nHours: " + hours.ToString(CultureInfo.InvariantCulture)
            + "\nValidated: " + (validated ? "true" : "false")
            + "\nTotal: $" + total.ToString("F2", CultureInfo.InvariantCulture);
    }

    // This method produces receipts for each nonblank input line.
    public static string CreateReport(IEnumerable<string> lines)
    {
        // This guard rejects a missing sequence before enumeration.
        if (lines is null)
        {
            throw new ArgumentNullException(nameof(lines));
        }

        // This loop skips blank entries and allows receipt format errors to propagate.
        var receipts = new List<string>();
        foreach (var line in lines)
        {
            // This guard skips null values and lines containing only whitespace.
            if (line is null || line.Trim().Length == 0)
            {
                continue;
            }

            // This call validates and formats the current nonblank entry.
            receipts.Add(CreateReceipt(line));
        }

        // This return joins the receipts with exactly one newline separator.
        return string.Join("\n", receipts);
    }

    // This method calculates a fee for a valid vehicle class and duration.
    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        // This guard rejects durations outside the supported range.
        if (hours < 1 || hours > 168)
        {
            throw new ArgumentOutOfRangeException(nameof(hours));
        }

        // This guard rejects a missing vehicle class using the pricing API contract.
        if (vehicleClass is null)
        {
            throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
        }

        // This normalization permits case-insensitive class names and surrounding spaces.
        var normalizedClass = vehicleClass.Trim().ToLowerInvariant();

        // This check resolves the configured rate or rejects an unknown class.
        if (!TryGetRate(normalizedClass, out var hourlyRate))
        {
            throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
        }

        // This loop prices each 24-hour block independently, including any partial block.
        decimal subtotal = 0m;
        var remainingHours = hours;
        while (remainingHours > 0)
        {
            // This assignment limits the current pricing block to at most 24 hours.
            var blockHours = Math.Min(24, remainingHours);

            // This calculation applies the three hourly tiers within the current block.
            decimal blockTotal = 0m;
            for (var hour = 1; hour <= blockHours; hour++)
            {
                // This branch charges the first two hours at the base rate.
                if (hour <= 2)
                {
                    blockTotal += hourlyRate;
                }
                // This branch charges hours three through five at one and a half times the rate.
                else if (hour <= 5)
                {
                    blockTotal += hourlyRate * 1.5m;
                }
                // This branch charges later hours at twice the rate.
                else
                {
                    blockTotal += hourlyRate * 2m;
                }
            }

            // This guard caps each block's charge at 24 base-rate hours.
            var blockCap = hourlyRate * 24m;
            if (blockTotal > blockCap)
            {
                blockTotal = blockCap;
            }

            // These updates add the block and advance to the next one.
            subtotal += blockTotal;
            remainingHours -= blockHours;
        }

        // This block applies the validation discount before tax.
        if (validated)
        {
            subtotal *= 0.90m;
        }

        // This calculation adds tax and rounds the final amount to cents.
        var total = subtotal * 1.08m;
        return Math.Round(total, 2, MidpointRounding.AwayFromZero);
    }

    // This helper returns the hourly rate for a normalized vehicle class.
    private static bool TryGetRate(string vehicleClass, out decimal rate)
    {
        // This switch maps each supported class to its base hourly rate.
        switch (vehicleClass)
        {
            case "car":
                rate = 5m;
                return true;
            case "motorcycle":
                rate = 3m;
                return true;
            case "van":
                rate = 8m;
                return true;
            default:
                rate = 0m;
                return false;
        }
    }
}
