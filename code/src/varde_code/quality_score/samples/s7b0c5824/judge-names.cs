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

        var orderItems = new List<OrderItem>();
        var encounteredSkus = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        decimal unroundedSubtotal = 0m;
        var inputLines = input.Split('\n');
        foreach (var inputLine in inputLines)
        {
            if (string.IsNullOrWhiteSpace(inputLine))
            {
                continue;
            }

            var rowFields = inputLine.Split('|');
            if (rowFields.Length != 3)
            {
                throw new ArgumentException("Each row needs three fields", nameof(input));
            }

            var stockKeepingUnit = rowFields[0].Trim();
            var quantityText = rowFields[1].Trim();
            var unitPriceText = rowFields[2].Trim();
            if (stockKeepingUnit.Length == 0)
            {
                throw new ArgumentException("SKU is required", nameof(input));
            }

            if (!encounteredSkus.Add(stockKeepingUnit))
            {
                throw new ArgumentException("SKUs must be unique", nameof(input));
            }

            int itemQuantity;
            decimal parsedUnitPrice;
            if (!int.TryParse(quantityText, NumberStyles.Integer, CultureInfo.InvariantCulture, out itemQuantity))
            {
                throw new ArgumentException("Quantity is invalid", nameof(input));
            }

            if (!decimal.TryParse(unitPriceText, NumberStyles.Number, CultureInfo.InvariantCulture, out parsedUnitPrice))
            {
                throw new ArgumentException("Price is invalid", nameof(input));
            }

            if (itemQuantity < 1 || itemQuantity > 100 || parsedUnitPrice < 0m || parsedUnitPrice > 10000m)
            {
                throw new ArgumentException("Value is outside the allowed range", nameof(input));
            }

            var roundedLineTotal = RoundCurrencyAmount(parsedUnitPrice * itemQuantity);
            orderItems.Add(new OrderItem(stockKeepingUnit, itemQuantity, RoundCurrencyAmount(parsedUnitPrice), roundedLineTotal));
            unroundedSubtotal += roundedLineTotal;
        }

        if (orderItems.Count == 0)
        {
            throw new ArgumentException("No order rows were found", nameof(input));
        }

        unroundedSubtotal = RoundCurrencyAmount(unroundedSubtotal);
        decimal orderDiscount = 0m;
        if (unroundedSubtotal >= 100m) orderDiscount = RoundCurrencyAmount(unroundedSubtotal * .10m);
        else if (unroundedSubtotal >= 50m) orderDiscount = RoundCurrencyAmount(unroundedSubtotal * .05m);
        var discountedSubtotal = RoundCurrencyAmount(unroundedSubtotal - orderDiscount);
        decimal taxAmount;
        if (discountedSubtotal > 0m)
        {
            taxAmount = RoundCurrencyAmount(discountedSubtotal * .0825m);
        }
        else
        {
            taxAmount = 0m;
        }

        decimal shippingAmount = 0m;
        if (discountedSubtotal < 25m)
        {
            if (discountedSubtotal >= 0m)
            {
                if (discountedSubtotal < 10m)
                {
                    shippingAmount = 8.95m;
                }
                else
                {
                    shippingAmount = 8.95m;
                }
            }
        }
        else
        {
            if (discountedSubtotal < 75m)
            {
                if (discountedSubtotal >= 25m)
                {
                    shippingAmount = 5.95m;
                }
                else
                {
                    shippingAmount = 8.95m;
                }
            }
            else
            {
                if (discountedSubtotal >= 75m)
                {
                    shippingAmount = 0m;
                }
                else
                {
                    shippingAmount = 5.95m;
                }
            }
        }
        var orderTotal = RoundCurrencyAmount(
            discountedSubtotal
            + taxAmount
            + shippingAmount);
        return new OrderResult(orderItems.AsReadOnly(), unroundedSubtotal, orderDiscount, taxAmount, shippingAmount, orderTotal);
    }

    public static string Report(OrderResult order)
    {
        if (order is null)
        {
            throw new ArgumentNullException(nameof(order));
        }

        var reportTextBuilder = new StringBuilder();
        reportTextBuilder.AppendLine("Order");
        reportTextBuilder.Append("Items: ")
            .Append(order.Items.Count)
            .AppendLine();
        reportTextBuilder.Append("Subtotal: $")
            .Append(FormatCurrencyAmount(order.Subtotal))
            .AppendLine();
        reportTextBuilder.Append("Discount: $")
            .Append(FormatCurrencyAmount(order.Discount))
            .AppendLine();
        reportTextBuilder.Append("Tax: $")
            .Append(FormatCurrencyAmount(order.Tax))
            .AppendLine();
        reportTextBuilder.Append("Shipping: $")
            .Append(FormatCurrencyAmount(order.Shipping))
            .AppendLine();
        reportTextBuilder.Append("Total: $")
            .Append(FormatCurrencyAmount(order.Total));
        return reportTextBuilder.ToString().TrimEnd('\r', '\n');
    }

    private static decimal RoundCurrencyAmount(decimal currencyAmount)
    {
        return Math.Round(
            currencyAmount,
            2,
            MidpointRounding.AwayFromZero);
    }

    private static string FormatCurrencyAmount(decimal currencyAmount)
    {
        return currencyAmount.ToString(
            "0.00",
            CultureInfo.InvariantCulture);
    }
}
