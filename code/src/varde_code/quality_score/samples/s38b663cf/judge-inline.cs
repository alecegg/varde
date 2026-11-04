using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass)
    {
        string value = seatClass == null ? string.Empty : seatClass.Trim();
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return 50m;
        if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return 90m;
        if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return 140m;
        return 0m;
    }

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        string value = seatClass == null ? string.Empty : seatClass.Trim();
        decimal unitPrice = 0m;
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase)) unitPrice = 50m;
        else if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase)) unitPrice = 90m;
        else if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase)) unitPrice = 140m;
        if (unitPrice == 0m || quantity < 1 || quantity > 20) return 0m;

        decimal subtotal = decimal.Round(unitPrice * quantity, 2, MidpointRounding.AwayFromZero);
        decimal discount = quantity >= 6 ? decimal.Round(subtotal * .10m, 2, MidpointRounding.AwayFromZero) : 0m;
        decimal discounted = subtotal - discount;
        decimal fee = discounted <= 100m ? 5m : discounted <= 500m ? 10m : 20m;
        decimal tax = decimal.Round((discounted + fee) * .08m, 2, MidpointRounding.AwayFromZero);
        return decimal.Round(discounted + fee + tax, 2, MidpointRounding.AwayFromZero);
    }

    public static string ProcessLine(string input)
    {
        if (input == null) return "REJECTED: format";
        string[] fields = input.Split('|');
        if (fields.Length != 3) return "REJECTED: format";
        string name = fields[0].Trim();
        string seatClass = fields[1].Trim();
        string quantityText = fields[2].Trim();
        if (name.Length == 0) return "REJECTED: name";

        string canonicalClass = string.Empty;
        decimal unitPrice = 0m;
        if (seatClass.Equals("Standard", StringComparison.OrdinalIgnoreCase))
        {
            canonicalClass = "Standard";
            unitPrice = 50m;
        }
        else if (seatClass.Equals("Premium", StringComparison.OrdinalIgnoreCase))
        {
            canonicalClass = "Premium";
            unitPrice = 90m;
        }
        else if (seatClass.Equals("VIP", StringComparison.OrdinalIgnoreCase))
        {
            canonicalClass = "VIP";
            unitPrice = 140m;
        }
        if (canonicalClass.Length == 0) return "REJECTED: class";
        if (!int.TryParse(quantityText, NumberStyles.Integer, CultureInfo.InvariantCulture, out int quantity) || quantity < 1 || quantity > 20)
            return "REJECTED: quantity";

        decimal subtotal = decimal.Round(unitPrice * quantity, 2, MidpointRounding.AwayFromZero);
        decimal discount = quantity >= 6 ? decimal.Round(subtotal * .10m, 2, MidpointRounding.AwayFromZero) : 0m;
        decimal discounted = subtotal - discount;
        decimal fee = discounted <= 100m ? 5m : discounted <= 500m ? 10m : 20m;
        decimal taxable = discounted + fee;
        decimal tax = decimal.Round(taxable * .08m, 2, MidpointRounding.AwayFromZero);
        decimal total = decimal.Round(taxable + tax, 2, MidpointRounding.AwayFromZero);
        return "CONFIRMED: " + name + "\n" +
            "Tickets: " + quantity.ToString(CultureInfo.InvariantCulture) + " x " + canonicalClass + "\n" +
            "Subtotal: $" + subtotal.ToString("0.00", CultureInfo.InvariantCulture) + "\n" +
            "Discount: $" + discount.ToString("0.00", CultureInfo.InvariantCulture) + "\n" +
            "Booking fee: $" + fee.ToString("0.00", CultureInfo.InvariantCulture) + "\n" +
            "Tax: $" + tax.ToString("0.00", CultureInfo.InvariantCulture) + "\n" +
            "Total: $" + total.ToString("0.00", CultureInfo.InvariantCulture);
    }

    public static string ProcessAll(string input)
    {
        if (string.IsNullOrEmpty(input)) return string.Empty;
        List<string> reports = new();
        using StringReader reader = new(input);
        string? line;
        while ((line = reader.ReadLine()) != null)
            if (line.Trim().Length > 0) reports.Add(ProcessLine(line));
        return string.Join("\n", reports);
    }
}
