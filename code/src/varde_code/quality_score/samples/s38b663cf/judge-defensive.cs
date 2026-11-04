using System.Globalization;

public static class Original
{
    // Return the unit price for a recognized seat class.
    public static decimal SeatPrice(string seatClass)
    {
        // A missing class cannot match a supported class.
        if (seatClass is null)
        {
            return 0m;
        }

        // Normalize whitespace before comparing class names.
        string className = seatClass.Trim();

        // Match each supported class without regard to letter casing.
        if (className.Equals("Standard", StringComparison.OrdinalIgnoreCase))
        {
            return 50m;
        }

        // Match each supported class without regard to letter casing.
        if (className.Equals("Premium", StringComparison.OrdinalIgnoreCase))
        {
            return 90m;
        }

        // Match each supported class without regard to letter casing.
        if (className.Equals("VIP", StringComparison.OrdinalIgnoreCase))
        {
            return 140m;
        }

        // Unknown class names have no ticket price.
        return 0m;
    }

    // Compute the final charge only when class and quantity are valid.
    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        // Reject a null or unsupported class before doing monetary work.
        if (seatClass is null)
        {
            return 0m;
        }

        // Reject quantities outside the booking limits.
        if (quantity < 1 || quantity > 20)
        {
            return 0m;
        }

        // Reject a class with no configured price.
        decimal unitPrice = SeatPrice(seatClass);
        if (unitPrice == 0m)
        {
            return 0m;
        }

        // Calculate the rounded ticket subtotal.
        decimal subtotal = Round(unitPrice * quantity);

        // Apply the group discount only at the required quantity threshold.
        decimal discount = quantity >= 6 ? Round(subtotal * 0.10m) : 0m;

        // Calculate the fee and tax from the discounted subtotal.
        decimal discountedSubtotal = subtotal - discount;
        decimal fee = Fee(discountedSubtotal);
        decimal taxableAmount = discountedSubtotal + fee;
        decimal tax = Round(taxableAmount * 0.08m);

        // Return the final amount rounded to currency precision.
        return Round(taxableAmount + tax);
    }

    // Validate and format one booking request.
    public static string ProcessLine(string input)
    {
        // A null request does not contain the required three fields.
        if (input is null)
        {
            return Reject("format");
        }

        // Require exactly name, class, and quantity fields.
        string[] fields = input.Split('|');
        if (fields is null || fields.Length != 3)
        {
            return Reject("format");
        }

        // Trim each value so surrounding whitespace does not affect validation.
        string name = fields[0]?.Trim() ?? string.Empty;
        string suppliedClass = fields[1]?.Trim() ?? string.Empty;
        string quantityText = fields[2]?.Trim() ?? string.Empty;

        // Require a nonblank customer name.
        if (name.Length == 0)
        {
            return Reject("name");
        }

        // Convert a supported class into its canonical display spelling.
        string canonicalClass = Canonical(suppliedClass);
        if (canonicalClass.Length == 0)
        {
            return Reject("class");
        }

        // Require an integer quantity within the booking limits.
        if (!int.TryParse(quantityText, NumberStyles.Integer, CultureInfo.InvariantCulture, out int quantity) || quantity < 1 || quantity > 20)
        {
            return Reject("quantity");
        }

        // Calculate each monetary component using the shared pricing rules.
        decimal subtotal = Round(SeatPrice(canonicalClass) * quantity);
        decimal discount = quantity >= 6 ? Round(subtotal * 0.10m) : 0m;
        decimal discountedSubtotal = subtotal - discount;
        decimal fee = Fee(discountedSubtotal);
        decimal taxableAmount = discountedSubtotal + fee;
        decimal tax = Round(taxableAmount * 0.08m);
        decimal total = Round(taxableAmount + tax);

        // Build the confirmation in the required line order and format.
        return "CONFIRMED: " + name + "\n" +
               "Tickets: " + quantity.ToString(CultureInfo.InvariantCulture) + " x " + canonicalClass + "\n" +
               "Subtotal: $" + Money(subtotal) + "\n" +
               "Discount: $" + Money(discount) + "\n" +
               "Booking fee: $" + Money(fee) + "\n" +
               "Tax: $" + Money(tax) + "\n" +
               "Total: $" + Money(total);
    }

    // Process each nonblank input line in its original order.
    public static string ProcessAll(string input)
    {
        // A missing or empty batch has no booking requests.
        if (input is null || input.Length == 0)
        {
            return string.Empty;
        }

        // Collect report blocks while skipping whitespace-only lines.
        List<string> reports = new();
        using StringReader reader = new(input);
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            // Ignore blank lines and preserve each nonblank request's result.
            if (!string.IsNullOrWhiteSpace(line))
            {
                reports.Add(ProcessLine(line));
            }
        }

        // Separate report blocks with one newline.
        return string.Join("\n", reports);
    }

    // Return the canonical spelling for a supported class.
    private static string Canonical(string value)
    {
        // A missing value cannot be a supported class.
        if (value is null)
        {
            return string.Empty;
        }

        // Map supported names to their display spelling.
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase))
        {
            return "Standard";
        }

        // Map supported names to their display spelling.
        if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase))
        {
            return "Premium";
        }

        // Map supported names to their display spelling.
        if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase))
        {
            return "VIP";
        }

        // Signal that no supported class matched.
        return string.Empty;
    }

    // Select the booking fee from the discounted ticket subtotal.
    private static decimal Fee(decimal amount)
    {
        // Use the lowest fee through one hundred dollars.
        if (amount <= 100m)
        {
            return 5m;
        }

        // Use the middle fee through five hundred dollars.
        if (amount <= 500m)
        {
            return 10m;
        }

        // Use the highest fee above five hundred dollars.
        return 20m;
    }

    // Apply the required currency rounding rule.
    private static decimal Round(decimal value)
    {
        // Round midpoint values away from zero to two decimal places.
        return decimal.Round(value, 2, MidpointRounding.AwayFromZero);
    }

    // Format a currency amount with invariant decimal punctuation.
    private static string Money(decimal value)
    {
        // Keep output stable regardless of the current culture.
        return value.ToString("0.00", CultureInfo.InvariantCulture);
    }

    // Create the exact rejection response for a validation reason.
    private static string Reject(string reason)
    {
        // Prefix the supplied reason with the required response text.
        return "REJECTED: " + reason;
    }
}
