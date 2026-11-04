using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public sealed record OrderItem(string Sku, int Quantity, decimal UnitPrice, decimal LineTotal);
public sealed record OrderResult(IReadOnlyList<OrderItem> Items, decimal Subtotal, decimal Discount, decimal Tax, decimal Shipping, decimal Total);

public static class Original
{
    private sealed class OrderState
    {
        public List<OrderItem> Items { get; } = new();
        public HashSet<string> Skus { get; } = new(StringComparer.OrdinalIgnoreCase);
        public decimal Subtotal { get; set; }
        public decimal Discount { get; set; }
        public decimal Net { get; set; }
        public decimal Tax { get; set; }
        public decimal Shipping { get; set; }
        public decimal Total { get; set; }
    }

    public static OrderResult Process(string input)
    {
        CheckInput(input);
        var state = CreateState();
        ReadRows(input, state);
        RoundSubtotal(state);
        ApplyPriceRules(state);
        return CreateResult(state);
    }

    private static void CheckInput(string input)
    {
        if (string.IsNullOrWhiteSpace(input)) throw new ArgumentException("Input is empty", nameof(input));
    }

    private static OrderState CreateState() => new();

    private static void ReadRows(string input, OrderState state)
    {
        foreach (var row in input.Split('\n')) ReadRow(row, state);
    }

    private static void ReadRow(string row, OrderState state)
    {
        if (string.IsNullOrWhiteSpace(row)) return;
        ProcessFields(SplitColumns(row), state);
    }

    private static void ProcessFields(string[] fields, OrderState state)
    {
        CheckColumns(fields);
        var sku = ReadSku(fields);
        CheckSku(sku, state);
        StoreFields(fields, sku, state);
    }

    private static void StoreFields(string[] fields, string sku, OrderState state)
    {
        var quantity = ReadQuantity(fields);
        var price = ReadPrice(fields);
        CheckValues(quantity, price);
        AddProduct(state, sku, quantity, price);
    }

    private static string[] SplitColumns(string row) => row.Split('|');

    private static void CheckColumns(string[] fields)
    {
        if (fields.Length != 3) throw new ArgumentException("Each row needs three fields", "input");
    }

    private static string ReadSku(string[] fields) => fields[0].Trim();

    private static void CheckSku(string sku, OrderState state)
    {
        if (sku.Length == 0) throw new ArgumentException("SKU is required", "input");
        if (!state.Skus.Add(sku)) throw new ArgumentException("SKUs must be unique", "input");
    }

    private static int ReadQuantity(string[] fields)
    {
        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            throw new ArgumentException("Quantity is invalid", "input");
        return quantity;
    }

    private static decimal ReadPrice(string[] fields)
    {
        if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var price))
            throw new ArgumentException("Price is invalid", "input");
        return price;
    }

    private static void CheckValues(int quantity, decimal price)
    {
        if (quantity < 1 || quantity > 100 || price < 0m || price > 10000m)
            throw new ArgumentException("Value is outside the allowed range", "input");
    }

    private static void AddProduct(OrderState state, string sku, int quantity, decimal price)
    {
        var lineTotal = AddLineAmount(price, quantity);
        var unitPrice = Math.Round(price, 2, MidpointRounding.AwayFromZero);
        state.Items.Add(new OrderItem(sku, quantity, unitPrice, lineTotal));
        state.Subtotal += lineTotal;
    }

    private static decimal AddLineAmount(decimal price, int quantity) =>
        Math.Round(price * quantity, 2, MidpointRounding.AwayFromZero);

    private static void ApplyPriceRules(OrderState state)
    {
        state.Discount = FindReduction(state.Subtotal);
        state.Net = ReduceAmount(state.Subtotal, state.Discount);
        state.Tax = AddTax(state.Net);
        state.Shipping = FindCarriage(state.Net);
        state.Total = AddFinalAmount(state.Net, state.Tax, state.Shipping);
    }

    private static void RoundSubtotal(OrderState state) =>
        state.Subtotal = Math.Round(state.Subtotal, 2, MidpointRounding.AwayFromZero);

    private static decimal FindReduction(decimal subtotal)
    {
        if (subtotal >= 100m) return Math.Round(subtotal * 0.10m, 2, MidpointRounding.AwayFromZero);
        if (subtotal >= 50m) return Math.Round(subtotal * 0.05m, 2, MidpointRounding.AwayFromZero);
        return 0m;
    }

    private static decimal ReduceAmount(decimal subtotal, decimal discount) =>
        Math.Round(subtotal - discount, 2, MidpointRounding.AwayFromZero);

    private static decimal AddTax(decimal net) =>
        Math.Round(net * 0.0825m, 2, MidpointRounding.AwayFromZero);

    private static decimal FindCarriage(decimal net)
    {
        if (net < 25m) return 8.95m;
        if (net < 75m) return 5.95m;
        return 0m;
    }

    private static decimal AddFinalAmount(decimal net, decimal tax, decimal shipping) =>
        Math.Round(net + tax + shipping, 2, MidpointRounding.AwayFromZero);

    private static OrderResult CreateResult(OrderState state)
    {
        if (state.Items.Count == 0) throw new ArgumentException("No order rows were found", "input");
        return new OrderResult(state.Items.AsReadOnly(), state.Subtotal, state.Discount, state.Tax, state.Shipping, state.Total);
    }

    public static string Report(OrderResult order)
    {
        CheckOrder(order);
        var report = StartReport();
        AppendReportContents(report, order);
        return TrimReport(report);
    }

    private static void AppendReportContents(StringBuilder report, OrderResult order)
    {
        AddCount(report, order);
        AddSubtotal(report, order);
        AddDiscount(report, order);
        AddTaxLine(report, order);
        AddShipping(report, order);
        AddTotal(report, order);
    }

    private static void CheckOrder(OrderResult order)
    {
        if (order is null) throw new ArgumentNullException(nameof(order));
    }

    private static StringBuilder StartReport()
    {
        var report = new StringBuilder();
        report.AppendLine("Order");
        return report;
    }

    private static void AddCount(StringBuilder report, OrderResult order) =>
        report.Append("Items: ").Append(order.Items.Count).AppendLine();

    private static void AddSubtotal(StringBuilder report, OrderResult order) => AppendMoney(report, "Subtotal", order.Subtotal);

    private static void AddDiscount(StringBuilder report, OrderResult order) => AppendMoney(report, "Discount", order.Discount);

    private static void AddTaxLine(StringBuilder report, OrderResult order) => AppendMoney(report, "Tax", order.Tax);

    private static void AddShipping(StringBuilder report, OrderResult order) => AppendMoney(report, "Shipping", order.Shipping);

    private static void AddTotal(StringBuilder report, OrderResult order)
    {
        report.Append("Total: $").Append(FormatMoney(order.Total));
    }

    private static void AppendMoney(StringBuilder report, string label, decimal amount)
    {
        report.Append(label).Append(": $").Append(FormatMoney(amount)).AppendLine();
    }

    private static string FormatMoney(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);

    private static string TrimReport(StringBuilder report) => report.ToString().TrimEnd('\r', '\n');
}
