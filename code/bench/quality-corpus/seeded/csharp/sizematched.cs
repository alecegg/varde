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
        if (string.IsNullOrWhiteSpace(input)) throw new ArgumentException("Input is empty", nameof(input));
        var rounding = MidpointRounding.AwayFromZero;
        var products = new List<OrderItem>();
        var identifiers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        decimal amount = 0m;
        foreach (var current in input.Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(current)) continue;
            var columns = current.Split('|');
            if (columns.Length != 3) throw new ArgumentException("Each row needs three fields", nameof(input));
            var code = columns[0].Trim();
            if (code.Length == 0) throw new ArgumentException("SKU is required", nameof(input));
            if (!identifiers.Add(code)) throw new ArgumentException("SKUs must be unique", nameof(input));
            if (!int.TryParse(columns[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var count))
                throw new ArgumentException("Quantity is invalid", nameof(input));
            if (!decimal.TryParse(columns[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var cost))
                throw new ArgumentException("Price is invalid", nameof(input));
            if (count < 1 || count > 100 || cost < 0m || cost > 10000m)
                throw new ArgumentException("Value is outside the allowed range", nameof(input));
            var extended = Math.Round(cost * count, 2, rounding);
            products.Add(new OrderItem(code, count, Math.Round(cost, 2, rounding), extended));
            amount += extended;
        }
        if (products.Count == 0) throw new ArgumentException("No order rows were found", nameof(input));
        amount = Math.Round(amount, 2, rounding);
        var reduction = amount >= 100m ? Math.Round(amount * 0.10m, 2, rounding) :
            amount >= 50m ? Math.Round(amount * 0.05m, 2, rounding) : 0m;
        var payable = Math.Round(amount - reduction, 2, rounding);
        var levy = Math.Round(payable * 0.0825m, 2, rounding);
        var carriage = payable < 25m ? 8.95m : payable < 75m ? 5.95m : 0m;
        return new OrderResult(products.AsReadOnly(), amount, reduction, levy, carriage,
            Math.Round(payable + levy + carriage, 2, rounding));
    }

    public static string Report(OrderResult order)
    {
        if (order is null) throw new ArgumentNullException(nameof(order));
        var text = new StringBuilder();
        text.AppendLine("Order");
        text.Append("Items: ").Append(order.Items.Count).AppendLine();
        text.Append("Subtotal: $").Append(order.Subtotal.ToString("0.00", CultureInfo.InvariantCulture)).AppendLine();
        text.Append("Discount: $").Append(order.Discount.ToString("0.00", CultureInfo.InvariantCulture)).AppendLine();
        text.Append("Tax: $").Append(order.Tax.ToString("0.00", CultureInfo.InvariantCulture)).AppendLine();
        text.Append("Shipping: $").Append(order.Shipping.ToString("0.00", CultureInfo.InvariantCulture)).AppendLine();
        text.Append("Total: $").Append(order.Total.ToString("0.00", CultureInfo.InvariantCulture));
        return text.ToString().TrimEnd('\r', '\n');
    }
}
