using System.Globalization;

public static class BehaviourTest
{
    private static int failures;
    private static int checks;

    public static int Main()
    {
        Equal(5.40m, Original.CalculateFee("car", 1, false));
        Equal(10.80m, Original.CalculateFee("car", 2, false));
        Equal(18.90m, Original.CalculateFee("car", 3, false));
        Equal(35.10m, Original.CalculateFee("car", 5, false));
        Equal(45.90m, Original.CalculateFee("car", 6, false));
        Equal(129.60m, Original.CalculateFee("car", 24, false));
        Equal(129.60m, Original.CalculateFee("car", 24, true) / 0.9m);
        Equal(259.20m, Original.CalculateFee("car", 48, false));
        Equal(5.40m, Original.CalculateFee("CAR", 1, false));
        Equal(3.24m, Original.CalculateFee("motorcycle", 1, false));
        Equal(8.64m, Original.CalculateFee("van", 1, false));
        Equal(4.86m, Original.CalculateFee("car", 1, true));
        Equal(816.48m, Original.CalculateFee("car", 168, true));
        Throws<ArgumentOutOfRangeException>(() => Original.CalculateFee("car", 0, false));
        Throws<ArgumentOutOfRangeException>(() => Original.CalculateFee("car", 169, false));
        Throws<ArgumentException>(() => Original.CalculateFee("bus", 1, false));
        Throws<FormatException>(() => Original.CreateReceipt(""));
        Throws<FormatException>(() => Original.CreateReceipt("car,1"));
        Throws<FormatException>(() => Original.CreateReceipt("bus,1,false"));
        Throws<FormatException>(() => Original.CreateReceipt("car,0,false"));
        Throws<FormatException>(() => Original.CreateReceipt("car,169,false"));
        Throws<FormatException>(() => Original.CreateReceipt("car,1,yes"));
        Equal("Vehicle: motorcycle\nHours: 3\nValidated: true\nTotal: $10.21", Original.CreateReceipt(" MOTORCYCLE , 3 , TRUE "));
        Equal("Vehicle: van\nHours: 1\nValidated: false\nTotal: $8.64", Original.CreateReceipt("van,1,false"));
        var report = Original.CreateReport(new[] { "car,1,false", "  ", "van,1,true" });
        Equal("Vehicle: car\nHours: 1\nValidated: false\nTotal: $5.40\nVehicle: van\nHours: 1\nValidated: true\nTotal: $7.78", report);
        Equal("", Original.CreateReport(Array.Empty<string>()));
        Throws<FormatException>(() => Original.CreateReport(new[] { "car,1,false", "nope" }));
        Equal(0m, ParseAmount("Vehicle: car\nHours: 1\nValidated: false\nTotal: $5.40") - 5.40m);
        if (failures > 0)
        {
            Console.Error.WriteLine($"{failures} of {checks} checks failed.");
            return 1;
        }
        Console.WriteLine($"{checks} checks passed.");
        return 0;
    }

    private static void Equal<T>(T expected, T actual)
    {
        checks++;
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            failures++;
            Console.Error.WriteLine($"Expected {expected}; got {actual}.");
        }
    }

    private static void Throws<T>(Action action) where T : Exception
    {
        checks++;
        try
        {
            action();
            failures++;
            Console.Error.WriteLine($"Expected {typeof(T).Name}.");
        }
        catch (T)
        {
        }
        catch (Exception ex)
        {
            failures++;
            Console.Error.WriteLine($"Expected {typeof(T).Name}; got {ex.GetType().Name}.");
        }
    }

    private static decimal ParseAmount(string receipt)
    {
        var marker = "Total: $";
        var start = receipt.LastIndexOf(marker, StringComparison.Ordinal) + marker.Length;
        return decimal.Parse(receipt.Substring(start), CultureInfo.InvariantCulture);
    }
}
