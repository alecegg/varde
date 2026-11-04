using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public sealed record OrderItem(string Sku, int Quantity, decimal UnitPrice, decimal LineTotal);
public sealed record OrderResult(IReadOnlyList<OrderItem> Items, decimal Subtotal, decimal Discount, decimal Tax, decimal Shipping, decimal Total);

public static class Original
{
    private sealed class OrderProcessingContext
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
        ValidateOrderText(input);
        var state = InitializeOrderState();
        ConsumeInputLines(input, state);
        NormalizeSubtotal(state);
        CalculateOrderCharges(state);
        return BuildOrderResult(state);
    }

    private static void ValidateOrderText(string input)
    {
        if (string.IsNullOrWhiteSpace(input)) throw new ArgumentException("Input is empty", nameof(input));
    }

    private static OrderProcessingContext InitializeOrderState() => new();

    private static void ConsumeInputLines(string input, OrderProcessingContext state)
    {
        foreach (var row in input.Split('\n')) HandleInputLine(row, state);
    }

    private static void HandleInputLine(string row, OrderProcessingContext state)
    {
        if (string.IsNullOrWhiteSpace(row)) return;
        InterpretItemFields(SeparateItemFields(row), state);
    }

    private static void InterpretItemFields(string[] fields, OrderProcessingContext state)
    {
        RequireThreeFields(fields);
        var sku = ExtractSku(fields);
        RegisterSku(sku, state);
        StoreItemFields(fields, sku, state);
    }

    private static void StoreItemFields(string[] fields, string sku, OrderProcessingContext state)
    {
        var quantity = ParseQuantityField(fields);
        var price = ParsePriceField(fields);
        ValidateItemValues(quantity, price);
        StoreOrderItem(state, sku, quantity, price);
    }

    private static string[] SeparateItemFields(string row) => row.Split('|');

    private static void RequireThreeFields(string[] fields)
    {
        if (fields.Length != 3) throw new ArgumentException("Each row needs three fields", "input");
    }

    private static string ExtractSku(string[] fields) => fields[0].Trim();

    private static void RegisterSku(string sku, OrderProcessingContext state)
    {
        if (sku.Length == 0) throw new ArgumentException("SKU is required", "input");
        if (!state.Skus.Add(sku)) throw new ArgumentException("SKUs must be unique", "input");
    }

    private static int ParseQuantityField(string[] fields)
    {
        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var quantity))
            throw new ArgumentException("Quantity is invalid", "input");
        return quantity;
    }

    private static decimal ParsePriceField(string[] fields)
    {
        if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var price))
            throw new ArgumentException("Price is invalid", "input");
        return price;
    }

    private static void ValidateItemValues(int quantity, decimal price)
    {
        if (quantity < 1 || quantity > 100 || price < 0m || price > 10000m)
            throw new ArgumentException("Value is outside the allowed range", "input");
    }

    private static void StoreOrderItem(OrderProcessingContext state, string sku, int quantity, decimal price)
    {
        var lineTotal = CalculateLineAmount(price, quantity);
        var unitPrice = Math.Round(price, 2, MidpointRounding.AwayFromZero);
        state.Items.Add(new OrderItem(sku, quantity, unitPrice, lineTotal));
        state.Subtotal += lineTotal;
    }

    private static decimal CalculateLineAmount(decimal price, int quantity) =>
        Math.Round(price * quantity, 2, MidpointRounding.AwayFromZero);

    private static void CalculateOrderCharges(OrderProcessingContext state)
    {
        state.Discount = CalculateDiscount(state.Subtotal);
        state.Net = SubtractDiscount(state.Subtotal, state.Discount);
        state.Tax = CalculateOrderTax(state.Net);
        state.Shipping = CalculateShippingFee(state.Net);
        state.Total = CalculateGrandTotal(state.Net, state.Tax, state.Shipping);
    }

    private static void NormalizeSubtotal(OrderProcessingContext state) =>
        state.Subtotal = Math.Round(state.Subtotal, 2, MidpointRounding.AwayFromZero);

    private static decimal CalculateDiscount(decimal subtotal)
    {
        if (subtotal >= 100m) return Math.Round(subtotal * 0.10m, 2, MidpointRounding.AwayFromZero);
        if (subtotal >= 50m) return Math.Round(subtotal * 0.05m, 2, MidpointRounding.AwayFromZero);
        return 0m;
    }

    private static decimal SubtractDiscount(decimal subtotal, decimal discount) =>
        Math.Round(subtotal - discount, 2, MidpointRounding.AwayFromZero);

    private static decimal CalculateOrderTax(decimal net) =>
        Math.Round(net * 0.0825m, 2, MidpointRounding.AwayFromZero);

    private static decimal CalculateShippingFee(decimal net)
    {
        if (net < 25m) return 8.95m;
        if (net < 75m) return 5.95m;
        return 0m;
    }

    private static decimal CalculateGrandTotal(decimal net, decimal tax, decimal shipping) =>
        Math.Round(net + tax + shipping, 2, MidpointRounding.AwayFromZero);

    private static OrderResult BuildOrderResult(OrderProcessingContext state)
    {
        if (state.Items.Count == 0) throw new ArgumentException("No order rows were found", "input");
        return new OrderResult(state.Items.AsReadOnly(), state.Subtotal, state.Discount, state.Tax, state.Shipping, state.Total);
    }

    public static string Report(OrderResult order)
    {
        ValidateReportArgument(order);
        var report = CreateReportBuffer();
        WriteReportSections(report, order);
        return FinishReportText(report);
    }

    private static void WriteReportSections(StringBuilder report, OrderResult order)
    {
        WriteItemCount(report, order);
        WriteSubtotal(report, order);
        WriteDiscount(report, order);
        WriteTax(report, order);
        WriteShipping(report, order);
        WriteTotal(report, order);
    }

    private static void ValidateReportArgument(OrderResult order)
    {
        if (order is null) throw new ArgumentNullException(nameof(order));
    }

    private static StringBuilder CreateReportBuffer()
    {
        var report = new StringBuilder();
        report.AppendLine("Order");
        return report;
    }

    private static void WriteItemCount(StringBuilder report, OrderResult order) =>
        report.Append("Items: ").Append(order.Items.Count).AppendLine();

    private static void WriteSubtotal(StringBuilder report, OrderResult order) => WriteCurrencyLine(report, "Subtotal", order.Subtotal);

    private static void WriteDiscount(StringBuilder report, OrderResult order) => WriteCurrencyLine(report, "Discount", order.Discount);

    private static void WriteTax(StringBuilder report, OrderResult order) => WriteCurrencyLine(report, "Tax", order.Tax);

    private static void WriteShipping(StringBuilder report, OrderResult order) => WriteCurrencyLine(report, "Shipping", order.Shipping);

    private static void WriteTotal(StringBuilder report, OrderResult order)
    {
        report.Append("Total: $").Append(FormatCurrency(order.Total));
    }

    private static void WriteCurrencyLine(StringBuilder report, string label, decimal amount)
    {
        report.Append(label).Append(": $").Append(FormatCurrency(amount)).AppendLine();
    }

    private static string FormatCurrency(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);

    private static string FinishReportText(StringBuilder report) => report.ToString().TrimEnd('\r', '\n');
}
