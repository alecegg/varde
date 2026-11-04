using System.Globalization;

public static class Original
{
    public static string CreateReceipt(string line) => ReceiptRequest.Parse(line).Render();

    public static string CreateReport(IEnumerable<string> lines)
    {
        ArgumentNullException.ThrowIfNull(lines);
        return string.Join("\n", lines
            .Where(line => !string.IsNullOrWhiteSpace(line))
            .Select(CreateReceipt));
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated) =>
        new ParkingSession(VehicleCatalog.Find(vehicleClass), hours, validated).CalculateFee();
}

internal sealed class ReceiptRequest
{
    private readonly ParkingSession session;

    private ReceiptRequest(ParkingSession session) => this.session = session;

    public static ReceiptRequest Parse(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) throw new FormatException("Input is required.");
        var fields = line.Trim().Split(',');
        if (fields.Length != 3) throw new FormatException("Expected three fields.");

        var vehicleName = fields[0].Trim();
        if (!int.TryParse(fields[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var hours) || hours is < 1 or > 168)
            throw new FormatException("Hours must be an integer from 1 through 168.");
        var validationText = fields[2].Trim();
        if (!bool.TryParse(validationText, out var validated))
            throw new FormatException("Validation must be true or false.");

        try
        {
            return new ReceiptRequest(new ParkingSession(VehicleCatalog.Find(vehicleName), hours, validated));
        }
        catch (ArgumentException)
        {
            throw new FormatException("Unknown vehicle class.");
        }
    }

    public string Render() => new ReceiptFormatter().Format(session);
}

internal interface IVehicle
{
    string Name { get; }
    decimal HourlyRate { get; }
}

internal sealed class Vehicle : IVehicle
{
    public Vehicle(string name, decimal hourlyRate)
    {
        Name = name;
        HourlyRate = hourlyRate;
    }

    public string Name { get; }
    public decimal HourlyRate { get; }
}

internal static class VehicleCatalog
{
    private static readonly IReadOnlyDictionary<string, IVehicle> Vehicles =
        new Dictionary<string, IVehicle>(StringComparer.OrdinalIgnoreCase)
        {
            ["car"] = new Vehicle("car", 5m),
            ["motorcycle"] = new Vehicle("motorcycle", 3m),
            ["van"] = new Vehicle("van", 8m)
        };

    public static IVehicle Find(string vehicleClass)
    {
        var normalized = vehicleClass?.Trim() ?? string.Empty;
        if (Vehicles.TryGetValue(normalized, out var vehicle)) return vehicle;
        throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
    }
}

internal sealed class ParkingSession
{
    private readonly IVehicle vehicle;
    private readonly int hours;
    private readonly bool validated;

    public ParkingSession(IVehicle vehicle, int hours, bool validated)
    {
        if (hours is < 1 or > 168) throw new ArgumentOutOfRangeException(nameof(hours));
        this.vehicle = vehicle;
        this.hours = hours;
        this.validated = validated;
    }

    public string VehicleName => vehicle.Name;
    public int Hours => hours;
    public bool Validated => validated;

    public decimal CalculateFee() => new FeeCalculator().Calculate(vehicle.HourlyRate, hours, validated);
}

internal interface IHourlyRateStrategy
{
    decimal RateForHour(int hour, decimal baseRate);
}

internal sealed class TieredHourlyRate : IHourlyRateStrategy
{
    public decimal RateForHour(int hour, decimal baseRate) => hour switch
    {
        <= 2 => baseRate,
        <= 5 => baseRate * 1.5m,
        _ => baseRate * 2m
    };
}

internal sealed class FeeCalculator
{
    private readonly IHourlyRateStrategy hourlyRate = new TieredHourlyRate();

    public decimal Calculate(decimal baseRate, int hours, bool validated)
    {
        decimal total = 0m;
        var remaining = hours;
        while (remaining > 0)
        {
            var blockHours = Math.Min(24, remaining);
            var blockCharge = PriceBlock(baseRate, blockHours);
            total += Math.Min(blockCharge, baseRate * 24m);
            remaining -= blockHours;
        }

        if (validated) total *= 0.9m;
        return Math.Round(total * 1.08m, 2, MidpointRounding.AwayFromZero);
    }

    private decimal PriceBlock(decimal baseRate, int blockHours)
    {
        decimal charge = 0m;
        for (var hour = 1; hour <= blockHours; hour++)
            charge += hourlyRate.RateForHour(hour, baseRate);
        return charge;
    }
}

internal sealed class ReceiptFormatter
{
    public string Format(ParkingSession session) =>
        $"Vehicle: {session.VehicleName}\nHours: {session.Hours.ToString(CultureInfo.InvariantCulture)}\nValidated: {session.Validated.ToString().ToLowerInvariant()}\nTotal: ${session.CalculateFee().ToString("F2", CultureInfo.InvariantCulture)}";
}
