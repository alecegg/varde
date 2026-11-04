using System;
using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string inputLine) => EnterQuote(inputLine);
    public static string BuildReport(string input) => EnterReport(input);
    private static Quote EnterQuote(string input) => ReadLine(input);
    private static Quote ReadLine(string input) => ParseLine(input);
    private static Quote ParseLine(string input) => Calculate(ParseFields(input));
    private static string[] ParseFields(string input) => SplitLine(input);
    private static string[] SplitLine(string input) => CheckFields(input);
    private static string[] CheckFields(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var fields = input.Split(',');
        if (fields.Length != 3) throw new ArgumentException("Invalid input");
        return fields;
    }
    private static Quote Calculate(string[] fields) => Price(Validate(fields));
    private static Parcel Validate(string[] fields) => ReadNumbers(fields);
    private static Parcel ReadNumbers(string[] fields)
    {
        var weightText = TrimField(fields, 0);
        var zoneText = TrimField(fields, 1).ToUpperInvariant();
        var valueText = TrimField(fields, 2);
        if (!decimal.TryParse(weightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var weight)) throw new ArgumentException("Invalid weight");
        if (!decimal.TryParse(valueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var value)) throw new ArgumentException("Invalid value");
        return CheckRange(weight, zoneText, value);
    }
    private static string TrimField(string[] fields, int index) => fields[index].Trim();
    private static Parcel CheckRange(decimal weight, string zone, decimal value)
    {
        if (weight <= 0 || weight > 30 || value < 0) throw new ArgumentException("Out of range");
        return MakeParcel(weight, zone, value);
    }
    private static Parcel MakeParcel(decimal weight, string zone, decimal value) => new(weight, zone, value);
    private sealed record Parcel(decimal Weight, string Zone, decimal Value);
    private static Quote Price(Parcel parcel) => Components(parcel);
    private static Quote Components(Parcel parcel) => AddInsurance(parcel, Rates(parcel));
    private static RatesResult Rates(Parcel parcel) => new(BaseRate(parcel.Weight), ZoneRate(parcel.Zone));
    private sealed record RatesResult(decimal Base, decimal Zone);
    private static decimal BaseRate(decimal weight) => BaseTier(weight);
    private static decimal BaseTier(decimal weight)
    {
        if (weight <= 1) return 5m;
        return BaseUpper(weight);
    }
    private static decimal BaseUpper(decimal weight)
    {
        if (weight <= 5) return 8m;
        return BaseHigh(weight);
    }
    private static decimal BaseHigh(decimal weight)
    {
        if (weight <= 10) return 12m;
        return 20m;
    }
    private static decimal ZoneRate(string zone) => ZoneLocal(zone);
    private static decimal ZoneLocal(string zone)
    {
        if (zone == "LOCAL") return 0m;
        return ZoneDomestic(zone);
    }
    private static decimal ZoneDomestic(string zone)
    {
        if (zone == "DOMESTIC") return 4m;
        return ZoneInternational(zone);
    }
    private static decimal ZoneInternational(string zone)
    {
        if (zone == "INTERNATIONAL") return 15m;
        throw new ArgumentException("Invalid destination");
    }
    private static Quote AddInsurance(Parcel parcel, RatesResult rates) => MakeQuote(parcel, rates, FuelCharge(rates));
    private static decimal FuelCharge(RatesResult rates) => Round((rates.Base + rates.Zone) * .10m);
    private static Quote MakeQuote(Parcel parcel, RatesResult rates, decimal fuel) => AddInsuranceValue(parcel, rates, fuel);
    private static Quote AddInsuranceValue(Parcel parcel, RatesResult rates, decimal fuel)
    {
        var insurance = InsuranceCharge(parcel.Value);
        return FinishBase(rates, fuel, insurance);
    }
    private static decimal InsuranceCharge(decimal value) => Round(Math.Min(value * .01m, 50m));
    private static Quote FinishBase(RatesResult rates, decimal fuel, decimal insurance)
    {
        var subtotal = Round(rates.Base + rates.Zone + fuel + insurance);
        return TaxQuote(rates, fuel, insurance, subtotal);
    }
    private static Quote TaxQuote(RatesResult rates, decimal fuel, decimal insurance, decimal subtotal) => FinalQuote(rates, fuel, insurance, Round(subtotal * .08m));
    private static Quote FinalQuote(RatesResult rates, decimal fuel, decimal insurance, decimal tax) =>
        new(Round(rates.Base), Round(rates.Zone), fuel, insurance, tax, Round(rates.Base + rates.Zone + fuel + insurance + tax));
    private static decimal Round(decimal value) => Math.Round(value, 2, MidpointRounding.ToEven);
    private static string EnterReport(string input) => ReportLines(input);
    private static string ReportLines(string input)
    {
        if (input == null) throw new ArgumentException("Invalid input");
        var lines = input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var output = new System.Collections.Generic.List<string>();
        foreach (var line in lines) AppendReportLine(output, line);
        return string.Join("\n", output);
    }
    private static void AppendReportLine(System.Collections.Generic.List<string> output, string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        output.Add(FormatReport(output.Count + 1, QuoteLine(line)));
    }
    private static string FormatReport(int number, Quote quote) =>
        "Parcel " + number.ToString(CultureInfo.InvariantCulture) + ": " +
        Component("BASE", quote.Base) + " " + Component("ZONE", quote.Zone) + " " +
        Component("FUEL", quote.Fuel) + " " + Component("INSURANCE", quote.Insurance) + " " +
        Component("TAX", quote.Tax) + " " + Component("TOTAL", quote.Total);
    private static string Component(string name, decimal value) => name + "=" + MoneyText(value);
    private static string MoneyText(decimal value) => value.ToString("0.00", CultureInfo.InvariantCulture);
}
