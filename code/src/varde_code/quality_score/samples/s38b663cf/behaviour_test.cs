using System;

public static class BehaviourTest
{
    private static int checks;

    public static int Main()
    {
        Check(Original.SeatPrice("Standard") == 50m, "standard price");
        Check(Original.SeatPrice(" premium ") == 90m, "trimmed premium price");
        Check(Original.SeatPrice("vIp") == 140m, "case insensitive vip price");
        Check(Original.SeatPrice("Balcony") == 0m, "unknown price");
        Check(Original.CalculateTotal("Standard", 1) == 59.40m, "small total");
        Check(Original.CalculateTotal("Standard", 2) == 113.40m, "middle fee tier");
        Check(Original.CalculateTotal("Standard", 20) == 993.60m, "high fee tier and discount");
        Check(Original.CalculateTotal("VIP", 6) == 838.08m, "vip group total");
        Check(Original.CalculateTotal("Other", 2) == 0m, "invalid class total");
        Check(Original.CalculateTotal("VIP", 0) == 0m, "invalid quantity total");
        Check(Original.CalculateTotal("VIP", 21) == 0m, "quantity upper bound");
        Check(Original.ProcessLine(" Ada | premium | 2 ") ==
            "CONFIRMED: Ada\nTickets: 2 x Premium\nSubtotal: $180.00\nDiscount: $0.00\nBooking fee: $10.00\nTax: $15.20\nTotal: $205.20", "confirmation report");
        Check(Original.ProcessLine("  |VIP|1") == "REJECTED: name", "blank name");
        Check(Original.ProcessLine("Ada|balcony|1") == "REJECTED: class", "unsupported class");
        Check(Original.ProcessLine("Ada|VIP|abc") == "REJECTED: quantity", "noninteger quantity");
        Check(Original.ProcessLine("Ada|VIP|21") == "REJECTED: quantity", "out of range quantity");
        Check(Original.ProcessLine("Ada|VIP") == "REJECTED: format", "missing field");
        Check(Original.ProcessLine("Ada|VIP|1|extra") == "REJECTED: format", "extra field");
        Check(Original.ProcessLine("Ada||1") == "REJECTED: class", "empty class");
        Check(Original.ProcessLine("Ada|Standard|1.0") == "REJECTED: quantity", "decimal quantity");
        string all = Original.ProcessAll("\nAda|Standard|1\n  \nBob|VIP|1\n");
        Check(all.StartsWith("CONFIRMED: Ada\n", StringComparison.Ordinal), "first input preserved");
        Check(all.Contains("\nCONFIRMED: Bob\n", StringComparison.Ordinal), "second input preserved");
        Check(!all.Contains("REJECTED", StringComparison.Ordinal), "blank input omitted");
        Check(Original.ProcessAll("") == string.Empty, "empty batch");
        Check(Original.ProcessAll("  \n") == string.Empty, "blank batch");
        Console.WriteLine(checks + " checks passed");
        return 0;
    }

    private static void Check(bool condition, string label)
    {
        checks++;
        if (!condition)
        {
            Console.Error.WriteLine("Check failed: " + label);
            Environment.ExitCode = 1;
            throw new InvalidOperationException(label);
        }
    }
}
