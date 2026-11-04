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
    public static OrderResult Process(string input)
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

            var lineTotal = Math.Round(unitPrice * quantity, 2, MidpointRounding.AwayFromZero);
            items.Add(new OrderItem(sku, quantity, Math.Round(unitPrice, 2, MidpointRounding.AwayFromZero), lineTotal));
            subtotal += lineTotal;
        }

        if (items.Count == 0)
        {
            throw new ArgumentException("No order rows were found", nameof(input));
        }

        subtotal = Math.Round(subtotal, 2, MidpointRounding.AwayFromZero);
        var discount = subtotal >= 100m
            ? Math.Round(subtotal * 0.10m, 2, MidpointRounding.AwayFromZero)
            : subtotal >= 50m
                ? Math.Round(subtotal * 0.05m, 2, MidpointRounding.AwayFromZero)
                : 0m;
        var discountedSubtotal = Math.Round(subtotal - discount, 2, MidpointRounding.AwayFromZero);
        var tax = Math.Round(discountedSubtotal * 0.0825m, 2, MidpointRounding.AwayFromZero);
        var shipping = discountedSubtotal < 25m
            ? 8.95m
            : discountedSubtotal < 75m
                ? 5.95m
                : 0m;
        var total = Math.Round(discountedSubtotal + tax + shipping, 2, MidpointRounding.AwayFromZero);

        return new OrderResult(items.AsReadOnly(), subtotal, discount, tax, shipping, total);
    }

    public static string Report(OrderResult order)
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

    private static string FormatMoney(decimal amount) =>
        amount.ToString("0.00", CultureInfo.InvariantCulture);
}
