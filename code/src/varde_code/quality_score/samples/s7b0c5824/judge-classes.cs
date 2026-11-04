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
    private static readonly OrderProcessor Processor = new(
        new OrderRowParser(),
        new TieredDiscountPolicy(),
        new RateTaxPolicy(),
        new TieredShippingPolicy());
    private static readonly OrderReportFormatter ReportFormatter = new();

    public static OrderResult Process(string input) => Processor.Process(input);

    public static string Report(OrderResult order) => ReportFormatter.Format(order);
}

internal interface IOrderRowParser
{
    IReadOnlyList<OrderItem> Parse(string input);
}

internal interface IDiscountPolicy
{
    decimal Calculate(decimal subtotal);
}

internal interface ITaxPolicy
{
    decimal Calculate(decimal discountedSubtotal);
}

internal interface IShippingPolicy
{
    decimal Calculate(decimal discountedSubtotal);
}

internal sealed class OrderProcessor
{
    private readonly IOrderRowParser _rowParser;
    private readonly IDiscountPolicy _discountPolicy;
    private readonly ITaxPolicy _taxPolicy;
    private readonly IShippingPolicy _shippingPolicy;

    public OrderProcessor(
        IOrderRowParser rowParser,
        IDiscountPolicy discountPolicy,
        ITaxPolicy taxPolicy,
        IShippingPolicy shippingPolicy)
    {
        _rowParser = rowParser;
        _discountPolicy = discountPolicy;
        _taxPolicy = taxPolicy;
        _shippingPolicy = shippingPolicy;
    }

    public OrderResult Process(string input)
    {
        var items = _rowParser.Parse(input);
        var subtotal = Money.Round(items.Sum(item => item.LineTotal));
        var discount = _discountPolicy.Calculate(subtotal);
        var discountedSubtotal = Money.Round(subtotal - discount);
        var tax = _taxPolicy.Calculate(discountedSubtotal);
        var shipping = _shippingPolicy.Calculate(discountedSubtotal);
        var total = Money.Round(discountedSubtotal + tax + shipping);
        return new OrderResult(items, subtotal, discount, tax, shipping, total);
    }
}

internal sealed class OrderRowParser : IOrderRowParser
{
    public IReadOnlyList<OrderItem> Parse(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
            throw new ArgumentException("Input is empty", nameof(input));

        var items = new List<OrderItem>();
        var seenSkus = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in input.Split('\n'))
        {
            if (string.IsNullOrWhiteSpace(row))
                continue;
            items.Add(ParseRow(row, seenSkus, input));
        }

        if (items.Count == 0)
            throw new ArgumentException("No order rows were found", nameof(input));
        return items.AsReadOnly();
    }

    private static OrderItem ParseRow(string row, HashSet<string> seenSkus, string input)
    {
        var fields = row.Split('|');
        if (fields.Length != 3)
            throw new ArgumentException("Each row needs three fields", nameof(input));

        var sku = fields[0].Trim();
        if (sku.Length == 0)
            throw new ArgumentException("SKU is required", nameof(input));
        if (!seenSkus.Add(sku))
            throw new ArgumentException("SKUs must be unique", nameof(input));

        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            throw new ArgumentException("Quantity is invalid", nameof(input));
        if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var unitPrice))
            throw new ArgumentException("Price is invalid", nameof(input));
        if (quantity < 1 || quantity > 100 || unitPrice < 0m || unitPrice > 10000m)
            throw new ArgumentException("Value is outside the allowed range", nameof(input));

        return new OrderItem(sku, quantity, Money.Round(unitPrice), Money.Round(unitPrice * quantity));
    }
}

internal sealed class TieredDiscountPolicy : IDiscountPolicy
{
    public decimal Calculate(decimal subtotal)
    {
        if (subtotal >= 100m) return Money.Round(subtotal * 0.10m);
        if (subtotal >= 50m) return Money.Round(subtotal * 0.05m);
        return 0m;
    }
}

internal sealed class RateTaxPolicy : ITaxPolicy
{
    public decimal Calculate(decimal discountedSubtotal) =>
        discountedSubtotal > 0m ? Money.Round(discountedSubtotal * 0.0825m) : 0m;
}

internal sealed class TieredShippingPolicy : IShippingPolicy
{
    public decimal Calculate(decimal discountedSubtotal)
    {
        if (discountedSubtotal < 25m) return 8.95m;
        if (discountedSubtotal < 75m) return 5.95m;
        return 0m;
    }
}

internal sealed class OrderReportFormatter
{
    public string Format(OrderResult order)
    {
        ArgumentNullException.ThrowIfNull(order);
        var report = new StringBuilder();
        report.AppendLine("Order");
        report.Append("Items: ").Append(order.Items.Count).AppendLine();
        AppendAmount(report, "Subtotal", order.Subtotal);
        AppendAmount(report, "Discount", order.Discount);
        AppendAmount(report, "Tax", order.Tax);
        AppendAmount(report, "Shipping", order.Shipping);
        report.Append("Total: $").Append(Money.Format(order.Total));
        return report.ToString().TrimEnd('\r', '\n');
    }

    private static void AppendAmount(StringBuilder report, string label, decimal amount) =>
        report.Append(label).Append(": $").Append(Money.Format(amount)).AppendLine();
}

internal static class Money
{
    public static decimal Round(decimal amount) => Math.Round(amount, 2, MidpointRounding.AwayFromZero);

    public static string Format(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);
}
