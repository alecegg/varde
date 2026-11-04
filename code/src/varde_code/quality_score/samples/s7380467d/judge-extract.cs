using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string s)
    {
        var fields = ValidateShape(s);
        var weight = ParseWeight(fields);
        var value = ParseValue(fields);
        ValidateLimits(weight, value);
        return CalculateQuote(weight, value, ParseDestination(fields));
    }

    private static string[] ValidateShape(string input)
    {
        if (input == null) throw InvalidInput();
        var fields = SplitFields(input);
        if (HasWrongShape(fields)) throw InvalidInput();
        return fields;
    }

    private static ArgumentException InvalidInput() => new ArgumentException("Invalid input");
    private static string[] SplitFields(string input) => input.Split(',');
    private static bool HasWrongShape(string[] fields) => fields.Length != 3;
    private static string Field(string[] fields, int index) => fields[index].Trim();

    private static decimal ParseWeight(string[] fields)
    {
        if (!TryReadNumber(Field(fields, 0), out var weight)) throw new ArgumentException("Invalid weight");
        return weight;
    }

    private static decimal ParseValue(string[] fields)
    {
        if (!TryReadNumber(Field(fields, 2), out var value)) throw new ArgumentException("Invalid value");
        return value;
    }

    private static bool TryReadNumber(string text, out decimal value)
    {
        return decimal.TryParse(text, NumberStyles.Number, CultureInfo.InvariantCulture, out value);
    }

    private static void ValidateLimits(decimal weight, decimal value)
    {
        if (IsInvalidWeight(weight) || IsInvalidValue(value)) throw new ArgumentException("Out of range");
    }

    private static bool IsInvalidWeight(decimal weight) => weight <= 0 || weight > 30;
    private static bool IsInvalidValue(decimal value) => value < 0;

    private static string ParseDestination(string[] fields)
    {
        var destination = NormalizeDestination(Field(fields, 1));
        if (IsSupportedDestination(destination)) return destination;
        throw new ArgumentException("Invalid destination");
    }

    private static string NormalizeDestination(string destination) => destination.ToUpperInvariant();
    private static bool IsSupportedDestination(string destination) => destination == "LOCAL" || destination == "DOMESTIC" || destination == "INTERNATIONAL";

    private static Quote CalculateQuote(decimal weight, decimal value, string destination)
    {
        var baseRate = Round(BaseRate(weight));
        var zone = Round(ZoneRate(destination));
        var fuel = FuelPart(baseRate, zone);
        var insurance = InsurancePart(value);
        var tax = TaxPart(Round(baseRate + zone + fuel + insurance));
        return CreateQuote(baseRate, zone, fuel, insurance, tax);
    }

    private static decimal BaseRate(decimal weight)
    {
        if (weight <= 1) return 5m;
        if (weight <= 5) return 8m;
        if (weight <= 10) return 12m;
        return 20m;
    }

    private static decimal ZoneRate(string destination)
    {
        if (destination == "LOCAL") return 0m;
        if (destination == "DOMESTIC") return 4m;
        return 15m;
    }

    private static decimal FuelPart(decimal baseRate, decimal zone) => Round((baseRate + zone) * .10m);
    private static decimal InsurancePart(decimal value) => Round(Math.Min(value * .01m, 50m));
    private static decimal TaxPart(decimal subtotal) => Round(subtotal * .08m);
    private static decimal Round(decimal amount) => decimal.Round(amount, 2, MidpointRounding.ToEven);

    private static Quote CreateQuote(decimal baseRate, decimal zone, decimal fuel, decimal insurance, decimal tax)
    {
        return new Quote(baseRate, zone, fuel, insurance, tax, Round(baseRate + zone + fuel + insurance + tax));
    }

    public static string BuildReport(string input)
    {
        if (input == null) throw InvalidInput();
        return FormatLines(ParseParcels(SplitLines(input)));
    }

    private static string[] SplitLines(string input) => input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
    private static List<string> ParseParcels(string[] lines) => lines.Where(IsNotBlank).Select(FormatParcel).ToList();
    private static bool IsNotBlank(string line) => !string.IsNullOrWhiteSpace(line);
    private static string FormatParcel(string line) => FormatQuote(QuoteLine(line));

    private static string FormatLines(List<string> lines)
    {
        var numbered = NumberLines(lines);
        return string.Join("\n", numbered);
    }

    private static List<string> NumberLines(List<string> lines)
    {
        var numbered = new List<string>();
        for (var index = 0; index < lines.Count; index++) numbered.Add(AddParcelNumber(index + 1, lines[index]));
        return numbered;
    }

    private static string AddParcelNumber(int number, string line) => MakePrefix(number) + line;
    private static string MakePrefix(int number) => "Parcel " + number.ToString(CultureInfo.InvariantCulture) + ": ";

    private static string FormatQuote(Quote quote)
    {
        return JoinComponents(FormatBase(quote), FormatZone(quote), FormatFuel(quote), FormatInsurance(quote), FormatTax(quote), FormatTotal(quote));
    }

    private static string JoinComponents(string a, string b, string c, string d, string e, string f) => string.Join(" ", a, b, c, d, e, f);
    private static string FormatBase(Quote quote) => FormatComponent("BASE", quote.Base);
    private static string FormatZone(Quote quote) => FormatComponent("ZONE", quote.Zone);
    private static string FormatFuel(Quote quote) => FormatComponent("FUEL", quote.Fuel);
    private static string FormatInsurance(Quote quote) => FormatComponent("INSURANCE", quote.Insurance);
    private static string FormatTax(Quote quote) => FormatComponent("TAX", quote.Tax);
    private static string FormatTotal(Quote quote) => FormatComponent("TOTAL", quote.Total);
    private static string FormatComponent(string name, decimal amount) => name + "=" + FormatMoney(amount);
    private static string FormatMoney(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);
}
