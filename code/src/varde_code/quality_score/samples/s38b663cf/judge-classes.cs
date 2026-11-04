using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass) => BookingService.SeatPrice(seatClass);

    public static decimal CalculateTotal(string seatClass, int quantity) =>
        BookingService.CalculateTotal(seatClass, quantity);

    public static string ProcessLine(string input) => BookingService.ProcessLine(input);

    public static string ProcessAll(string input) => BookingService.ProcessAll(input);
}

internal static class BookingService
{
    public static decimal SeatPrice(string seatClass) =>
        TicketClass.Find(seatClass)?.Price ?? 0m;

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        var ticketClass = TicketClass.Find(seatClass);
        if (ticketClass == null || !TicketQuantity.IsValid(quantity)) return 0m;
        return new Booking(ticketClass, quantity).Calculate().Total;
    }

    public static string ProcessLine(string input)
    {
        if (!BookingRequest.TryParse(input, out var request, out var error))
            return BookingReport.Rejected(error);

        var booking = new Booking(request.TicketClass, request.Quantity);
        return BookingReport.Confirmed(request, booking.Calculate());
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

    internal static TicketClass? FindClass(string value) => TicketClass.Find(value);
}

internal sealed class TicketClass
{
    public string Name { get; }
    public decimal Price { get; }

    public TicketClass(string name, decimal price)
    {
        Name = name;
        Price = price;
    }

    public static TicketClass? Find(string value)
    {
        var cleaned = value?.Trim() ?? string.Empty;
        return BookingClassCatalog.Find(cleaned);
    }
}

internal static class BookingClassCatalog
{
    private static readonly IReadOnlyList<TicketClass> Classes = new[]
    {
        new TicketClass("Standard", 50m),
        new TicketClass("Premium", 90m),
        new TicketClass("VIP", 140m)
    };

    public static TicketClass? Find(string name) =>
        Classes.FirstOrDefault(item =>
            item.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
}

internal sealed class TicketQuantity
{
    public int Value { get; }
    public static bool IsValid(int value) => value >= 1 && value <= 20;

    public TicketQuantity(int value) => Value = value;
}

internal sealed class BookingRequest
{
    public string Name { get; }
    public TicketClass TicketClass { get; }
    public int Quantity { get; }

    private BookingRequest(string name, TicketClass ticketClass, int quantity)
    {
        Name = name;
        TicketClass = ticketClass;
        Quantity = quantity;
    }

    public static bool TryParse(string input, out BookingRequest request, out string error)
    {
        request = null!;
        error = "format";
        if (input == null) return false;
        var fields = input.Split('|');
        if (fields.Length != 3) return false;
        var name = fields[0].Trim();
        if (name.Length == 0) { error = "name"; return false; }
        var ticketClass = BookingService.FindClass(fields[1]);
        if (ticketClass == null) { error = "class"; return false; }
        if (!int.TryParse(fields[2].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity)
            || !TicketQuantity.IsValid(quantity))
        { error = "quantity"; return false; }
        request = new BookingRequest(name, ticketClass, quantity);
        error = string.Empty;
        return true;
    }
}

internal interface IDiscountStrategy
{
    decimal Calculate(decimal subtotal, int quantity);
}

internal sealed class GroupDiscount : IDiscountStrategy
{
    public decimal Calculate(decimal subtotal, int quantity) =>
        quantity >= 6 ? Currency.Round(subtotal * 0.10m) : 0m;
}

internal interface IBookingFeeStrategy
{
    decimal Calculate(decimal discountedSubtotal);
}

internal sealed class TieredBookingFee : IBookingFeeStrategy
{
    public decimal Calculate(decimal amount) =>
        amount <= 100m ? 5m : amount <= 500m ? 10m : 20m;
}

internal sealed class Booking
{
    private static readonly IDiscountStrategy Discount = new GroupDiscount();
    private static readonly IBookingFeeStrategy Fee = new TieredBookingFee();
    private readonly TicketClass _ticketClass;
    private readonly int _quantity;

    public Booking(TicketClass ticketClass, int quantity)
    {
        _ticketClass = ticketClass;
        _quantity = quantity;
    }

    public BookingAmounts Calculate()
    {
        var subtotal = Currency.Round(_ticketClass.Price * _quantity);
        var discount = Discount.Calculate(subtotal, _quantity);
        var discountedSubtotal = subtotal - discount;
        var fee = Fee.Calculate(discountedSubtotal);
        var tax = Currency.Round((discountedSubtotal + fee) * 0.08m);
        return new BookingAmounts(subtotal, discount, fee, tax,
            Currency.Round(discountedSubtotal + fee + tax));
    }
}

internal sealed class BookingAmounts
{
    public decimal Subtotal { get; }
    public decimal Discount { get; }
    public decimal Fee { get; }
    public decimal Tax { get; }
    public decimal Total { get; }

    public BookingAmounts(decimal subtotal, decimal discount, decimal fee, decimal tax, decimal total)
    {
        Subtotal = subtotal;
        Discount = discount;
        Fee = fee;
        Tax = tax;
        Total = total;
    }
}

internal static class BookingReport
{
    public static string Rejected(string reason) => "REJECTED: " + reason;

    public static string Confirmed(BookingRequest request, BookingAmounts amounts) =>
        "CONFIRMED: " + request.Name + "\n" +
        "Tickets: " + request.Quantity.ToString(CultureInfo.InvariantCulture) + " x " + request.TicketClass.Name + "\n" +
        "Subtotal: $" + Currency.Format(amounts.Subtotal) + "\n" +
        "Discount: $" + Currency.Format(amounts.Discount) + "\n" +
        "Booking fee: $" + Currency.Format(amounts.Fee) + "\n" +
        "Tax: $" + Currency.Format(amounts.Tax) + "\n" +
        "Total: $" + Currency.Format(amounts.Total);
}

internal static class Currency
{
    public static decimal Round(decimal amount) =>
        decimal.Round(amount, 2, MidpointRounding.AwayFromZero);

    public static string Format(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);
}
