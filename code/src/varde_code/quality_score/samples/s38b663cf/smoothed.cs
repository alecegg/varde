using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass) => PriceFor(Canonical(Clean(seatClass)));

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        decimal price = SeatPrice(seatClass);
        if (price == 0m || !IsValidQuantity(quantity)) return 0m;
        return CalculateAmounts(price, quantity).Total;
    }

    public static string ProcessLine(string input)
    {
        if (input == null) return Reject("format");

        string[] fields = input.Split('|');
        if (fields.Length != 3) return Reject("format");

        string name = fields[0].Trim();
        string seatClass = Canonical(fields[1].Trim());
        if (name.Length == 0) return Reject("name");
        if (seatClass.Length == 0) return Reject("class");
        if (!int.TryParse(fields[2].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int quantity)
            || !IsValidQuantity(quantity)) return Reject("quantity");

        Amounts amounts = CalculateAmounts(PriceFor(seatClass), quantity);
        return string.Join("\n", new[]
        {
            "CONFIRMED: " + name,
            "Tickets: " + quantity.ToString(CultureInfo.InvariantCulture) + " x " + seatClass,
            AmountLine("Subtotal", amounts.Subtotal),
            AmountLine("Discount", amounts.Discount),
            AmountLine("Booking fee", amounts.Fee),
            AmountLine("Tax", amounts.Tax),
            AmountLine("Total", amounts.Total)
        });
    }

    public static string ProcessAll(string input)
    {
        if (string.IsNullOrEmpty(input)) return string.Empty;

        var reports = new List<string>();
        using var reader = new StringReader(input);
        string? line;
        while ((line = reader.ReadLine()) != null)
            if (!string.IsNullOrWhiteSpace(line)) reports.Add(ProcessLine(line));
        return string.Join("\n", reports);
    }

    private static Amounts CalculateAmounts(decimal price, int quantity)
    {
        decimal subtotal = Round(price * quantity);
        decimal discount = quantity >= 6 ? Round(subtotal * 0.10m) : 0m;
        decimal discountedSubtotal = subtotal - discount;
        decimal fee = Fee(discountedSubtotal);
        decimal tax = Round((discountedSubtotal + fee) * 0.08m);
        decimal total = Round(discountedSubtotal + fee + tax);
        return new Amounts(subtotal, discount, fee, tax, total);
    }

    private static string Canonical(string value)
    {
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return "Standard";
        if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return "Premium";
        if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return "VIP";
        return string.Empty;
    }

    private static decimal PriceFor(string seatClass)
    {
        if (seatClass == "Standard") return 50m;
        if (seatClass == "Premium") return 90m;
        if (seatClass == "VIP") return 140m;
        return 0m;
    }

    private static bool IsValidQuantity(int quantity) => quantity >= 1 && quantity <= 20;

    private static decimal Fee(decimal amount)
    {
        if (amount <= 100m) return 5m;
        if (amount <= 500m) return 10m;
        return 20m;
    }

    private static decimal Round(decimal value) => decimal.Round(value, 2, MidpointRounding.AwayFromZero);

    private static string Money(decimal value) => value.ToString("0.00", CultureInfo.InvariantCulture);

    private static string AmountLine(string label, decimal amount) => label + ": $" + Money(amount);

    private static string Reject(string reason) => "REJECTED: " + reason;

    private static string Clean(string value) => value == null ? string.Empty : value.Trim();

    private readonly record struct Amounts(decimal Subtotal, decimal Discount, decimal Fee, decimal Tax, decimal Total);
}
