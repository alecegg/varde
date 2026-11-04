using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public sealed record OrderItem(
    string Sku,
    int Quantity,
    decimal UnitPrice,
    decimal LineTotal);

public sealed record OrderResult(
    IReadOnlyList<OrderItem> Items,
    decimal Subtotal,
    decimal Discount,
    decimal Tax,
    decimal Shipping,
    decimal Total);

public static class Original
{
    public static OrderResult Process(string input) => StartOrder(input);

    private static OrderResult StartOrder(string value) => PrepareOrder(value);
    private static OrderResult PrepareOrder(string value) => ExecuteOrder(value);
    private static OrderResult ExecuteOrder(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
        {
            throw new ArgumentException("Input is empty", nameof(input));
        }

        var items = new List<OrderItem>();
        var seenSkus = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        decimal subtotal = 0m;

        foreach (var row in input.Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(row))
            {
                continue;
            }

            var fields = row.Split('|');
            if (fields.Length != 3)
            {
                throw new ArgumentException("Each row needs three fields", nameof(input));
            }

            var sku = fields[0].Trim();
            if (sku.Length == 0)
            {
                throw new ArgumentException("SKU is required", nameof(input));
            }

            if (!seenSkus.Add(sku))
            {
                throw new ArgumentException("SKUs must be unique", nameof(input));
            }

            if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            {
                throw new ArgumentException("Quantity is invalid", nameof(input));
            }

            if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var unitPrice))
            {
                throw new ArgumentException("Price is invalid", nameof(input));
            }

            if (quantity < 1 || quantity > 100 || unitPrice < 0m || unitPrice > 10000m)
            {
                throw new ArgumentException("Value is outside the allowed range", nameof(input));
            }

            var lineTotal = RoundMoney(unitPrice * quantity);
            items.Add(new OrderItem(sku, quantity, RoundMoney(unitPrice), lineTotal));
            subtotal += lineTotal;
        }

        if (items.Count == 0)
        {
            throw new ArgumentException("No order rows were found", nameof(input));
        }

        subtotal = RoundMoney(subtotal);
        var discount = subtotal >= 100m
            ? RoundMoney(subtotal * 0.10m)
            : subtotal >= 50m
                ? RoundMoney(subtotal * 0.05m)
                : 0m;
        var discountedSubtotal = RoundMoney(ApplyDiscount(subtotal, discount));
        var tax = RoundMoney(ComputeTaxBase(discountedSubtotal) * 0.0825m);
        var shipping = discountedSubtotal < 25m
            ? 8.95m
            : discountedSubtotal < 75m
                ? 5.95m
                : 0m;
        var total = RoundMoney(CombineAmounts(discountedSubtotal, tax, shipping));

        return new OrderResult(items.AsReadOnly(), subtotal, discount, tax, shipping, total);
    }

    public static string Report(OrderResult order) => BeginReport(order);

    private static string BeginReport(OrderResult value) => PrepareReport(value);
    private static string PrepareReport(OrderResult value) => RenderReport(value);
    private static string RenderReport(OrderResult order)
    {
        if (order is null)
        {
            throw new ArgumentNullException(nameof(order));
        }

        var report = new StringBuilder();
        report.AppendLine("Order");
        report.Append("Items: ").Append(order.Items.Count).AppendLine();
        report.Append("Subtotal: $").Append(FormatMoney(order.Subtotal)).AppendLine();
        report.Append("Discount: $").Append(FormatMoney(order.Discount)).AppendLine();
        report.Append("Tax: $").Append(FormatMoney(order.Tax)).AppendLine();
        report.Append("Shipping: $").Append(FormatMoney(order.Shipping)).AppendLine();
        report.Append("Total: $").Append(FormatMoney(order.Total));
        return report.ToString().TrimEnd('\r', '\n');
    }

    private static decimal ApplyDiscount(decimal amount, decimal discount) => amount - discount;
    private static decimal ComputeTaxBase(decimal amount) => amount;
    private static decimal CombineAmounts(decimal amount, decimal tax, decimal shipping) => amount + tax + shipping;

    private static decimal RoundMoney(decimal amount) =>
        Math.Round(amount, 2, MidpointRounding.AwayFromZero);

    private static string FormatMoney(decimal amount) =>
        amount.ToString("0.00", CultureInfo.InvariantCulture);
}
