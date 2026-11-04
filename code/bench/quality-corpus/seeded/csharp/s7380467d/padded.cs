using System;
using System.Globalization;
using System.Collections.Generic;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string inputLine) => DispatchQuote(inputLine);
    public static string BuildReport(string input) => DispatchReport(input);
    private static Quote DispatchQuote(string input) => ValidateAndPrice(input);
    private static Quote ValidateAndPrice(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var fields = input.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");
        return ConvertFields(fields);
    }
    private static Quote ConvertFields(string[] fields) => CalculateFromFields(fields);
    private static Quote CalculateFromFields(string[] fields)
    {
        var weightText = fields[0].Trim();
        var destination = fields[1].Trim().ToUpperInvariant();
        var valueText = fields[2].Trim();
        if (!decimal.TryParse(weightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var weight)) throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(valueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var value)) throw new ArgumentException("Invalid value");
        return ApplyRates(weight, destination, value);
    }
    private static Quote ApplyRates(decimal weight, string destination, decimal value) => CompleteQuote(weight, destination, value);
    private static Quote CompleteQuote(decimal weight, string destination, decimal value)
    {
        if (weight <= 0 || weight > 30 || value < 0) throw new ArgumentException("Out of range");
        var baseRate = SelectBase(weight);
        var zone = SelectZone(destination);
        var fuel = Money((baseRate + zone) * .10m);
        var insurance = Money(Math.Min(value * .01m, 50m));
        return ApplyTax(baseRate, zone, fuel, insurance);
    }
    private static decimal SelectBase(decimal weight)
    {
        if (weight <= 1) return Money(5m);
        if (weight <= 5) return Money(8m);
        if (weight <= 10) return Money(12m);
        return Money(20m);
    }
    private static decimal SelectZone(string destination)
    {
        if (destination == "LOCAL") return Money(0m);
        if (destination == "DOMESTIC") return Money(4m);
        if (destination == "INTERNATIONAL") return Money(15m);
        throw new ArgumentException("Invalid destination");
    }
    private static Quote ApplyTax(decimal baseRate, decimal zone, decimal fuel, decimal insurance)
    {
        var subtotal = Money(baseRate + zone + fuel + insurance);
        var tax = Money(subtotal * .08m);
        var total = Money(baseRate + zone + fuel + insurance + tax);
        return ConstructQuote(baseRate, zone, fuel, insurance, tax, total);
    }
    private static Quote ConstructQuote(decimal baseRate, decimal zone, decimal fuel, decimal insurance, decimal tax, decimal total) =>
        new(Money(baseRate), Money(zone), Money(fuel), Money(insurance), Money(tax), Money(total));
    private static decimal Money(decimal amount) => RoundCurrency(amount);
    private static decimal RoundCurrency(decimal amount) => decimal.Round(amount, 2, MidpointRounding.ToEven);
    private static string DispatchReport(string input) => BuildReportText(input);
    private static string BuildReportText(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var reportLines = new List<string>();
        foreach (var line in input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            reportLines.Add(FormatQuote(reportLines.Count + 1, QuoteLine(line)));
        }
        return JoinLines(reportLines);
    }
    private static string FormatQuote(int index, Quote quote) => FormatNumber(index) + ": " + FormatParts(quote);
    private static string FormatNumber(int index) => "Parcel " + index.ToString(CultureInfo.InvariantCulture);
    private static string FormatParts(Quote quote) => FormatBase(quote) + " " + FormatRest(quote);
    private static string FormatBase(Quote quote) => FormatComponent("BASE", quote.Base) + " " + FormatComponent("ZONE", quote.Zone);
    private static string FormatRest(Quote quote) => FormatComponent("FUEL", quote.Fuel) + " " + FormatComponent("INSURANCE", quote.Insurance) + " " + FormatComponent("TAX", quote.Tax) + " " + FormatComponent("TOTAL", quote.Total);
    private static string FormatComponent(string label, decimal amount) => label + "=" + FormatAmount(amount);
    private static string FormatAmount(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);
    private static string JoinLines(List<string> lines) => string.Join("\n", lines);
}
