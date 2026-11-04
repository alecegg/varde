using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass)
    {
        return PriceFor(Canonical(Clean(seatClass)));
    }

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        if (!IsValidOrder(seatClass, quantity)) return 0m;
        return Total(SeatPrice(seatClass), quantity);
    }

    public static string ProcessLine(string input)
    {
        if (!TryParse(input, out var booking, out var error)) return Reject(error);
        return FormatReport(booking);
    }

    public static string ProcessAll(string input)
    {
        return string.Join("\n", NonblankLines(input).Select(ProcessLine));
    }

    private static bool TryParse(string input, out Booking booking, out string error)
    {
        booking = default;
        error = "format";
        if (input == null) return false;
        return TryParseFields(input.Split('|'), out booking, out error);
    }

    private static bool TryParseFields(string[] fields, out Booking booking, out string error)
    {
        booking = default;
        error = "format";
        if (fields.Length != 3) return false;
        return TryParseValues(fields[0].Trim(), fields[1].Trim(), fields[2].Trim(), out booking, out error);
    }

    private static bool TryParseValues(string name, string seatClass, string quantityText, out Booking booking, out string error)
    {
        booking = default;
        if (string.IsNullOrEmpty(name)) return Fail("name", out error);
        return TryParseClass(name, seatClass, quantityText, out booking, out error);
    }

    private static bool TryParseClass(string name, string seatClass, string quantityText, out Booking booking, out string error)
    {
        booking = default;
        string canonical = Canonical(seatClass);
        if (canonical.Length == 0) return Fail("class", out error);
        return TryParseQuantity(name, canonical, quantityText, out booking, out error);
    }

    private static bool TryParseQuantity(string name, string seatClass, string text, out Booking booking, out string error)
    {
        booking = default;
        error = "quantity";
        if (!int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int quantity)) return false;
        if (quantity < 1 || quantity > 20) return false;
        booking = new Booking(name, seatClass, quantity);
        error = string.Empty;
        return true;
    }

    private static bool Fail(string reason, out string error)
    {
        error = reason;
        return false;
    }

    private static string FormatReport(Booking booking)
    {
        return string.Join("\n", ReportLines(booking));
    }

    private static IEnumerable<string> ReportLines(Booking booking)
    {
        var amounts = AmountsFor(booking.SeatClass, booking.Quantity);
        yield return "CONFIRMED: " + booking.Name;
        yield return TicketLine(booking);
        yield return AmountLine("Subtotal", amounts.Subtotal);
        yield return AmountLine("Discount", amounts.Discount);
        yield return AmountLine("Booking fee", amounts.Fee);
        yield return AmountLine("Tax", amounts.Tax);
        yield return AmountLine("Total", amounts.Total);
    }

    private static string TicketLine(Booking booking)
    {
        return "Tickets: " + booking.Quantity.ToString(CultureInfo.InvariantCulture) + " x " + booking.SeatClass;
    }

    private static string AmountLine(string label, decimal amount)
    {
        return label + ": $" + Money(amount);
    }

    private static Amounts AmountsFor(string seatClass, int quantity)
    {
        decimal subtotal = Round(PriceFor(seatClass) * quantity);
        return CalculateAmounts(subtotal, quantity);
    }

    private static Amounts CalculateAmounts(decimal subtotal, int quantity)
    {
        decimal discount = Discount(subtotal, quantity);
        decimal afterDiscount = subtotal - discount;
        decimal fee = Fee(afterDiscount);
        decimal tax = Round((afterDiscount + fee) * .08m);
        return new Amounts(subtotal, discount, fee, tax, Round(afterDiscount + fee + tax));
    }

    private static decimal Total(decimal price, int quantity)
    {
        return AmountsForPrice(price, quantity).Total;
    }

    private static Amounts AmountsForPrice(decimal price, int quantity)
    {
        return CalculateAmounts(Round(price * quantity), quantity);
    }

    private static decimal Discount(decimal subtotal, int quantity)
    {
        return quantity >= 6 ? Round(subtotal * .10m) : 0m;
    }

    private static decimal PriceFor(string seatClass)
    {
        if (seatClass == "Standard") return 50m;
        if (seatClass == "Premium") return 90m;
        if (seatClass == "VIP") return 140m;
        return 0m;
    }

    private static string Canonical(string value)
    {
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return "Standard";
        if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return "Premium";
        if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return "VIP";
        return string.Empty;
    }

    private static bool IsValidOrder(string seatClass, int quantity)
    {
        return PriceFor(Canonical(Clean(seatClass))) != 0m && quantity >= 1 && quantity <= 20;
    }

    private static IEnumerable<string> NonblankLines(string input)
    {
        if (input == null) yield break;
        using var reader = new StringReader(input);
        foreach (string? line in ReadLines(reader))
            if (!string.IsNullOrWhiteSpace(line)) yield return line;
    }

    private static IEnumerable<string?> ReadLines(StringReader reader)
    {
        string? line;
        while ((line = reader.ReadLine()) != null) yield return line;
    }

    private static string Clean(string value)
    {
        return value == null ? string.Empty : value.Trim();
    }

    private static decimal Fee(decimal amount)
    {
        if (amount <= 100m) return 5m;
        if (amount <= 500m) return 10m;
        return 20m;
    }

    private static decimal Round(decimal value)
    {
        return decimal.Round(value, 2, MidpointRounding.AwayFromZero);
    }

    private static string Money(decimal value)
    {
        return value.ToString("0.00", CultureInfo.InvariantCulture);
    }

    private static string Reject(string reason)
    {
        return "REJECTED: " + reason;
    }

    private readonly record struct Booking(string Name, string SeatClass, int Quantity);
    private readonly record struct Amounts(decimal Subtotal, decimal Discount, decimal Fee, decimal Tax, decimal Total);
}
