using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string input) => ParcelQuoteService.Create().Quote(input);

    public static string BuildReport(string input) => new ParcelReportBuilder().Build(input);
}

internal sealed class ParcelQuoteService
{
    private readonly ParcelInputParser parser = new();
    private readonly WeightRateSchedule rates = new();
    private readonly DestinationSurchargeSchedule surcharges = new();
    private readonly QuoteCalculator calculator = new();

    public static ParcelQuoteService Create() => new();

    public Original.Quote Quote(string input)
    {
        var parcel = parser.Parse(input);
        return calculator.Calculate(parcel, rates.BaseFor(parcel.WeightKg), surcharges.For(parcel.Destination));
    }
}

internal sealed record Parcel(decimal WeightKg, ShippingDestination Destination, decimal DeclaredValue);

internal enum ShippingDestination
{
    Local,
    Domestic,
    International
}

internal sealed class ParcelInputParser
{
    public Parcel Parse(string input)
    {
        if (input is null) throw new ArgumentException("Invalid input");
        var fields = input.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");

        if (!decimal.TryParse(fields[0].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var weight))
            throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(fields[2].Trim(), NumberStyles.Number, CultureInfo.InvariantCulture, out var value))
            throw new ArgumentException("Invalid value");
        if (weight <= 0 || weight > 30 || value < 0) throw new ArgumentException("Out of range");

        return new Parcel(weight, ParseDestination(fields[1].Trim()), value);
    }

    private static ShippingDestination ParseDestination(string value)
    {
        return value.ToUpperInvariant() switch
        {
            "LOCAL" => ShippingDestination.Local,
            "DOMESTIC" => ShippingDestination.Domestic,
            "INTERNATIONAL" => ShippingDestination.International,
            _ => throw new ArgumentException("Invalid destination")
        };
    }
}

internal interface IBaseRateSchedule
{
    decimal BaseFor(decimal weightKg);
}

internal sealed class WeightRateSchedule : IBaseRateSchedule
{
    public decimal BaseFor(decimal weightKg)
    {
        if (weightKg <= 1) return 5m;
        if (weightKg <= 5) return 8m;
        if (weightKg <= 10) return 12m;
        return 20m;
    }
}

internal interface IDestinationSurchargeSchedule
{
    decimal For(ShippingDestination destination);
}

internal sealed class DestinationSurchargeSchedule : IDestinationSurchargeSchedule
{
    public decimal For(ShippingDestination destination) => destination switch
    {
        ShippingDestination.Local => 0m,
        ShippingDestination.Domestic => 4m,
        ShippingDestination.International => 15m,
        _ => throw new ArgumentOutOfRangeException(nameof(destination))
    };
}

internal sealed class QuoteCalculator
{
    public Original.Quote Calculate(Parcel parcel, decimal baseRate, decimal zoneRate)
    {
        var baseAmount = Money.Round(baseRate);
        var zoneAmount = Money.Round(zoneRate);
        var fuel = Money.Round((baseAmount + zoneAmount) * 0.10m);
        var insurance = Money.Round(Math.Min(parcel.DeclaredValue * 0.01m, 50m));
        var subtotal = Money.Round(baseAmount + zoneAmount + fuel + insurance);
        var tax = Money.Round(subtotal * 0.08m);
        var total = Money.Round(baseAmount + zoneAmount + fuel + insurance + tax);
        return new Original.Quote(baseAmount, zoneAmount, fuel, insurance, tax, total);
    }
}

internal static class Money
{
    public static decimal Round(decimal amount) => decimal.Round(amount, 2, MidpointRounding.ToEven);
    public static string Format(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);
}

internal sealed class ParcelReportBuilder
{
    public string Build(string input)
    {
        if (input is null) throw new ArgumentException("Invalid input");
        var lines = input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var output = new List<string>();
        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var quote = Original.QuoteLine(line);
            output.Add(FormatParcel(output.Count + 1, quote));
        }
        return string.Join("\n", output);
    }

    private static string FormatParcel(int number, Original.Quote quote) =>
        $"Parcel {number.ToString(CultureInfo.InvariantCulture)}: BASE={Money.Format(quote.Base)} ZONE={Money.Format(quote.Zone)} FUEL={Money.Format(quote.Fuel)} INSURANCE={Money.Format(quote.Insurance)} TAX={Money.Format(quote.Tax)} TOTAL={Money.Format(quote.Total)}";
}
