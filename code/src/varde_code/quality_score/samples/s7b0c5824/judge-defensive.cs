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
        // Reject an absent or blank request before allocating any order state.
        if (input is not string || string.IsNullOrWhiteSpace(input))
        {
            throw new ArgumentException("Input is empty", nameof(input));
        }

        // Keep insertion order in the list and use a case-insensitive set for SKU validation.
        var items = new List<OrderItem>();
        var seenSkus = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        decimal subtotal = 0m;

        // Parse each nonblank line independently so errors identify invalid order input.
        foreach (var rawLine in input.Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(rawLine))
            {
                continue;
            }

            // Require exactly the three fields specified by the input format.
            var fields = rawLine.Split('|');
            if (fields is not string[] || fields.Length != 3)
            {
                throw new ArgumentException("Each row needs three fields", nameof(input));
            }

            // Trim each field before validating or converting its value.
            var sku = fields[0].Trim();
            var quantityText = fields[1].Trim();
            var priceText = fields[2].Trim();
            if (sku is not string || sku.Length == 0)
            {
                throw new ArgumentException("SKU is required", nameof(input));
            }

            // Prevent duplicate products regardless of SKU letter casing.
            if (!seenSkus.Add(sku))
            {
                throw new ArgumentException("SKUs must be unique", nameof(input));
            }

            // Parse numeric text invariantly so results do not depend on machine locale.
            if (quantityText is not string || !int.TryParse(quantityText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            {
                throw new ArgumentException("Quantity is invalid", nameof(input));
            }

            if (priceText is not string || !decimal.TryParse(priceText, NumberStyles.Number, CultureInfo.InvariantCulture, out var unitPrice))
            {
                throw new ArgumentException("Price is invalid", nameof(input));
            }

            // Enforce supported quantity and price ranges before calculating a line.
            if (quantity < 1 || quantity > 100 || unitPrice < 0m || unitPrice > 10000m)
            {
                throw new ArgumentException("Value is outside the allowed range", nameof(input));
            }

            // Round each line total and preserve the trimmed unit price in the result.
            var lineTotal = RoundMoney(unitPrice * quantity);
            items.Add(new OrderItem(sku, quantity, RoundMoney(unitPrice), lineTotal));
            subtotal += lineTotal;
        }

        // Reject input that contained only blank lines instead of returning an empty order.
        if (items.Count == 0)
        {
            throw new ArgumentException("No order rows were found", nameof(input));
        }

        // Apply the single order discount based on the rounded pre-discount subtotal.
        subtotal = RoundMoney(subtotal);
        var discountRate = subtotal >= 100m ? 0.10m : subtotal >= 50m ? 0.05m : 0m;
        var discount = RoundMoney(subtotal * discountRate);
        var discountedSubtotal = RoundMoney(subtotal - discount);

        // Calculate tax and shipping from the discounted subtotal using the required tiers.
        var tax = RoundMoney(discountedSubtotal * 0.0825m);
        var shipping = discountedSubtotal < 25m ? 8.95m : discountedSubtotal < 75m ? 5.95m : 0m;
        var total = RoundMoney(discountedSubtotal + tax + shipping);

        // Return an immutable view of the items along with the calculated order amounts.
        return new OrderResult(items.AsReadOnly(), subtotal, discount, tax, shipping, total);
    }

    public static string Report(OrderResult order)
    {
        // Reject a missing order before reading its properties.
        if (order is not OrderResult)
        {
            throw new ArgumentNullException(nameof(order));
        }

        // Build the report in the required line order with invariant currency formatting.
        var builder = new StringBuilder();
        builder.AppendLine("Order");
        builder.Append("Items: ").Append(order.Items.Count).AppendLine();
        builder.Append("Subtotal: $").Append(FormatMoney(order.Subtotal)).AppendLine();
        builder.Append("Discount: $").Append(FormatMoney(order.Discount)).AppendLine();
        builder.Append("Tax: $").Append(FormatMoney(order.Tax)).AppendLine();
        builder.Append("Shipping: $").Append(FormatMoney(order.Shipping)).AppendLine();
        builder.Append("Total: $").Append(FormatMoney(order.Total));
        return builder.ToString().TrimEnd('\r', '\n');
    }

    private static decimal RoundMoney(decimal amount)
    {
        // Use two decimal places and the specified midpoint rule for every calculation.
        return Math.Round(amount, 2, MidpointRounding.AwayFromZero);
    }

    private static string FormatMoney(decimal amount)
    {
        // Format with fixed precision independently of the current culture.
        return amount.ToString("0.00", CultureInfo.InvariantCulture);
    }
}
