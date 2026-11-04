using System.Globalization;
using System.Text;

public sealed record OrderItem(string Sku, int Quantity, decimal UnitPrice, decimal LineTotal);

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
        ValidateInput(input);
        var items = ParseItems(input);
        var subtotal = Round(items.Sum(item => item.LineTotal));
        return BuildResult(items, subtotal);
    }

    private static void ValidateInput(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
            throw new ArgumentException("Input is empty", nameof(input));
    }

    private static List<OrderItem> ParseItems(string input)
    {
        var items = new List<OrderItem>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        AddRows(input, items, seen);
        EnsureItemsExist(items);
        return items;
    }

    private static void AddRows(string input, List<OrderItem> items, HashSet<string> seen)
    {
        foreach (var row in input.Split('\n'))
            AddNonblankRow(row, items, seen);
    }

    private static void AddNonblankRow(string row, List<OrderItem> items, HashSet<string> seen)
    {
        if (!string.IsNullOrWhiteSpace(row))
            items.Add(ParseRow(row, seen));
    }

    private static OrderItem ParseRow(string row, HashSet<string> seen)
    {
        var fields = GetFields(row);
        var sku = fields[0].Trim();
        ValidateSku(sku, seen);
        return MakeItem(sku, fields[1].Trim(), fields[2].Trim());
    }

    private static string[] GetFields(string row)
    {
        var fields = row.Split('|');
        if (fields.Length != 3)
            throw new ArgumentException("Each row needs three fields", "input");
        return fields;
    }

    private static void ValidateSku(string sku, HashSet<string> seen)
    {
        if (sku.Length == 0)
            throw new ArgumentException("SKU is required", "input");
        if (!seen.Add(sku))
            throw new ArgumentException("SKUs must be unique", "input");
    }

    private static OrderItem MakeItem(string sku, string quantityText, string priceText)
    {
        var quantity = ParseQuantity(quantityText);
        var price = ParsePrice(priceText);
        ValidateValues(quantity, price);
        return new OrderItem(sku, quantity, Round(price), Round(price * quantity));
    }

    private static int ParseQuantity(string value)
    {
        if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            return quantity;
        throw new ArgumentException("Quantity is invalid", "input");
    }

    private static decimal ParsePrice(string value)
    {
        if (decimal.TryParse(value, NumberStyles.Number, CultureInfo.InvariantCulture, out var price))
            return price;
        throw new ArgumentException("Price is invalid", "input");
    }

    private static void ValidateValues(int quantity, decimal price)
    {
        if (quantity < 1 || quantity > 100 || price < 0m || price > 10000m)
            throw new ArgumentException("Value is outside the allowed range", "input");
    }

    private static void EnsureItemsExist(List<OrderItem> items)
    {
        if (items.Count == 0)
            throw new ArgumentException("No order rows were found", "input");
    }

    private static OrderResult BuildResult(List<OrderItem> items, decimal subtotal)
    {
        var discount = GetDiscount(subtotal);
        var discounted = Round(subtotal - discount);
        var tax = GetTax(discounted);
        var shipping = GetShipping(discounted);
        return new OrderResult(items.AsReadOnly(), subtotal, discount, tax, shipping, Round(discounted + tax + shipping));
    }

    private static decimal GetDiscount(decimal subtotal)
    {
        if (subtotal >= 100m) return Round(subtotal * .10m);
        if (subtotal >= 50m) return Round(subtotal * .05m);
        return 0m;
    }

    private static decimal GetTax(decimal amount) => amount > 0m ? Round(amount * .0825m) : 0m;

    private static decimal GetShipping(decimal amount)
    {
        if (amount < 25m) return 8.95m;
        if (amount < 75m) return 5.95m;
        return 0m;
    }

    public static string Report(OrderResult order)
    {
        ArgumentNullException.ThrowIfNull(order);
        return ComposeReport(order);
    }

    private static string ComposeReport(OrderResult order)
    {
        var lines = ReportLines(order);
        return string.Join(Environment.NewLine, lines);
    }

    private static string[] ReportLines(OrderResult order) =>
    [
        "Order", "Items: " + order.Items.Count, CurrencyLine("Subtotal", order.Subtotal),
        CurrencyLine("Discount", order.Discount), CurrencyLine("Tax", order.Tax),
        CurrencyLine("Shipping", order.Shipping), CurrencyLine("Total", order.Total)
    ];

    private static string CurrencyLine(string label, decimal amount) => label + ": $" + Format(amount);

    private static string Format(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);

    private static decimal Round(decimal amount) => Math.Round(amount, 2, MidpointRounding.AwayFromZero);
}
