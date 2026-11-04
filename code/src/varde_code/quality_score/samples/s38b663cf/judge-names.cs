using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass)
    {
        string trimmedSeatClass = seatClass == null ? string.Empty : seatClass.Trim();
        if (trimmedSeatClass.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return 50m;
        if (trimmedSeatClass.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return 90m;
        if (trimmedSeatClass.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return 140m;
        return 0m;
    }

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        decimal perTicketPrice = SeatPrice(seatClass);
        if (perTicketPrice == 0m || quantity < 1 || quantity > 20) return 0m;

        decimal ticketSubtotal = RoundCurrency(perTicketPrice * quantity);
        decimal groupDiscount = quantity >= 6 ? RoundCurrency(ticketSubtotal * 0.10m) : 0m;
        decimal discountedSubtotal = ticketSubtotal - groupDiscount;
        decimal bookingFee = CalculateBookingFee(discountedSubtotal);
        decimal taxableAmount = discountedSubtotal + bookingFee;
        decimal taxAmount = RoundCurrency(taxableAmount * 0.08m);
        return RoundCurrency(taxableAmount + taxAmount);
    }

    public static string ProcessLine(string input)
    {
        if (input == null) return CreateRejection("format");

        string[] requestFields = input.Split('|');
        if (requestFields.Length != 3) return CreateRejection("format");

        string customerName = requestFields[0].Trim();
        string requestedSeatClass = requestFields[1].Trim();
        string quantityText = requestFields[2].Trim();
        if (customerName.Length == 0) return CreateRejection("name");

        string canonicalSeatClass = GetCanonicalSeatClass(requestedSeatClass);
        if (canonicalSeatClass.Length == 0) return CreateRejection("class");

        if (!int.TryParse(quantityText, NumberStyles.Integer, CultureInfo.InvariantCulture, out int ticketQuantity)
            || ticketQuantity < 1 || ticketQuantity > 20)
            return CreateRejection("quantity");

        decimal perTicketPrice = SeatPrice(canonicalSeatClass);
        decimal ticketSubtotal = RoundCurrency(perTicketPrice * ticketQuantity);
        decimal groupDiscount = ticketQuantity >= 6 ? RoundCurrency(ticketSubtotal * 0.10m) : 0m;
        decimal discountedSubtotal = ticketSubtotal - groupDiscount;
        decimal bookingFee = CalculateBookingFee(discountedSubtotal);
        decimal taxableAmount = discountedSubtotal + bookingFee;
        decimal taxAmount = RoundCurrency(taxableAmount * 0.08m);
        decimal finalTotal = RoundCurrency(taxableAmount + taxAmount);

        string confirmationReport = "CONFIRMED: " + customerName + "\n";
        confirmationReport += "Tickets: " + ticketQuantity.ToString(CultureInfo.InvariantCulture) + " x " + canonicalSeatClass + "\n";
        confirmationReport += "Subtotal: $" + FormatCurrency(ticketSubtotal) + "\n";
        confirmationReport += "Discount: $" + FormatCurrency(groupDiscount) + "\n";
        confirmationReport += "Booking fee: $" + FormatCurrency(bookingFee) + "\n";
        confirmationReport += "Tax: $" + FormatCurrency(taxAmount) + "\n";
        confirmationReport += "Total: $" + FormatCurrency(finalTotal);
        return confirmationReport;
    }

    public static string ProcessAll(string input)
    {
        if (input == null || input.Length == 0) return string.Empty;

        var bookingReports = new List<string>();
        using (var inputReader = new StringReader(input))
        {
            string? requestLine;
            while ((requestLine = inputReader.ReadLine()) != null)
            {
                if (requestLine.Trim().Length > 0) bookingReports.Add(ProcessLine(requestLine));
            }
        }
        return string.Join("\n", bookingReports);
    }

    private static string GetCanonicalSeatClass(string seatClass)
    {
        if (seatClass.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return "Standard";
        if (seatClass.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return "Premium";
        if (seatClass.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return "VIP";
        return string.Empty;
    }

    private static decimal CalculateBookingFee(decimal discountedSubtotal)
    {
        if (discountedSubtotal <= 100m) return 5m;
        if (discountedSubtotal <= 500m) return 10m;
        return 20m;
    }

    private static decimal RoundCurrency(decimal currencyAmount)
    {
        return decimal.Round(currencyAmount, 2, MidpointRounding.AwayFromZero);
    }

    private static string FormatCurrency(decimal currencyAmount)
    {
        return currencyAmount.ToString("0.00", CultureInfo.InvariantCulture);
    }

    private static string CreateRejection(string rejectionReason)
    {
        return "REJECTED: " + rejectionReason;
    }
}
