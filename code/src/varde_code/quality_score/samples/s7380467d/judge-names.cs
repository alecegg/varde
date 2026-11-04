using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string inputLine)
    {
        if (IsMissingInput(inputLine)) throw new ArgumentException("Invalid input");
        var commaSeparatedFields = SplitCommaSeparatedFields(inputLine);
        if (HasIncorrectFieldCount(commaSeparatedFields)) throw new ArgumentException("Invalid input");
        var weightText = commaSeparatedFields[0].Trim();
        var normalizedDestination = commaSeparatedFields[1].Trim().ToUpperInvariant();
        var declaredValueText = commaSeparatedFields[2].Trim();
        decimal parcelWeightKilograms;
        decimal declaredValue;
        if (!TryParseInvariantDecimal(weightText, out parcelWeightKilograms)) throw new ArgumentException("Invalid weight");
        if (!TryParseInvariantDecimal(declaredValueText, out declaredValue)) throw new ArgumentException("Invalid value");
        if (AreValuesOutsideAllowedLimits(parcelWeightKilograms, declaredValue)) throw new ArgumentException("Out of range");
        decimal baseRate;
        if (parcelWeightKilograms <= 1) baseRate = 5m;
        else if (parcelWeightKilograms <= 5)
        {
            if (parcelWeightKilograms > 1) baseRate = 8m;
            else baseRate = 5m;
        }
        else if (parcelWeightKilograms <= 10) baseRate = 12m;
        else baseRate = 20m;
        decimal destinationSurcharge;
        if (normalizedDestination == "LOCAL") destinationSurcharge = 0m;
        else if (normalizedDestination == "DOMESTIC") destinationSurcharge = 4m;
        else if (normalizedDestination == "INTERNATIONAL") destinationSurcharge = 15m;
        else throw new ArgumentException("Invalid destination");
        baseRate = RoundCurrencyAmount(baseRate);
        destinationSurcharge = RoundCurrencyAmount(destinationSurcharge);
        var fuelSurcharge = CalculateFuelSurcharge(baseRate, destinationSurcharge);
        var insuranceCharge = CalculateInsuranceCharge(declaredValue);
        var taxableSubtotal = RoundCurrencyAmount(baseRate + destinationSurcharge + fuelSurcharge + insuranceCharge);
        var taxCharge = CalculateTaxCharge(taxableSubtotal);
        var totalCharge = CalculateTotalCharge(baseRate, destinationSurcharge, fuelSurcharge, insuranceCharge, taxCharge);
        return new Quote(baseRate, destinationSurcharge, fuelSurcharge, insuranceCharge, taxCharge, totalCharge);
    }

    public static string BuildReport(string input)
    {
        if (IsMissingInput(input)) throw new ArgumentException("Invalid input");
        var inputLines = SplitInputLines(input);
        var reportLines = new List<string>();
        var parcelNumber = 0;
        foreach (var inputLine in inputLines)
        {
            if (IsWhitespaceOnly(inputLine)) continue;
            var parcelQuote = QuoteLine(inputLine);
            parcelNumber++;
            reportLines.Add(FormatParcelPrefix(parcelNumber) + FormatBaseRate(parcelQuote.Base) + " " + FormatDestinationSurcharge(parcelQuote.Zone) + " " + FormatFuelSurcharge(parcelQuote.Fuel) + " " + FormatInsuranceCharge(parcelQuote.Insurance) + " " + FormatTaxCharge(parcelQuote.Tax) + " " + FormatTotalCharge(parcelQuote.Total));
        }
        return string.Join("\n", reportLines);
    }

    private static decimal RoundCurrencyAmount(decimal amount) => decimal.Round(amount, 2, MidpointRounding.ToEven);
    private static string FormatInvariantCurrency(decimal amount) => amount.ToString("0.00", CultureInfo.InvariantCulture);

    private static bool IsMissingInput(string input) => input == null;

    private static string[] SplitCommaSeparatedFields(string input)
    {
        return input.Split(',');
    }

    private static bool HasIncorrectFieldCount(string[] fields)
    {
        return fields.Length != 3;
    }

    private static bool TryParseInvariantDecimal(string numericText, out decimal parsedAmount)
    {
        return decimal.TryParse(numericText, NumberStyles.Number, CultureInfo.InvariantCulture, out parsedAmount);
    }

    private static bool AreValuesOutsideAllowedLimits(decimal parcelWeightKilograms, decimal declaredValue)
    {
        return parcelWeightKilograms <= 0 || parcelWeightKilograms > 30 || declaredValue < 0;
    }

    private static decimal CalculateFuelSurcharge(decimal baseRate, decimal destinationSurcharge)
    {
        return RoundCurrencyAmount((baseRate + destinationSurcharge) * .10m);
    }

    private static decimal CalculateInsuranceCharge(decimal declaredValue)
    {
        return RoundCurrencyAmount(Math.Min(declaredValue * .01m, 50m));
    }

    private static decimal CalculateTaxCharge(decimal taxableSubtotal)
    {
        return RoundCurrencyAmount(taxableSubtotal * .08m);
    }

    private static decimal CalculateTotalCharge(decimal baseRate, decimal destinationSurcharge, decimal fuelSurcharge, decimal insuranceCharge, decimal taxCharge)
    {
        return RoundCurrencyAmount(baseRate + destinationSurcharge + fuelSurcharge + insuranceCharge + taxCharge);
    }

    private static string[] SplitInputLines(string input)
    {
        return input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
    }

    private static bool IsWhitespaceOnly(string inputLine)
    {
        return inputLine.Trim().Length == 0;
    }

    private static string FormatParcelPrefix(int parcelNumber)
    {
        return "Parcel " + parcelNumber.ToString(CultureInfo.InvariantCulture) + ": ";
    }

    private static string FormatMoneyAmount(decimal amount)
    {
        return FormatInvariantCurrency(amount);
    }

    private static string FormatBaseRate(decimal baseRate)
    {
        return "BASE=" + FormatMoneyAmount(baseRate);
    }

    private static string FormatDestinationSurcharge(decimal destinationSurcharge)
    {
        return "ZONE=" + FormatMoneyAmount(destinationSurcharge);
    }

    private static string FormatFuelSurcharge(decimal fuelSurcharge)
    {
        return "FUEL=" + FormatMoneyAmount(fuelSurcharge);
    }

    private static string FormatInsuranceCharge(decimal insuranceCharge)
    {
        return "INSURANCE=" + FormatMoneyAmount(insuranceCharge);
    }

    private static string FormatTaxCharge(decimal taxCharge)
    {
        return "TAX=" + FormatMoneyAmount(taxCharge);
    }

    private static string FormatTotalCharge(decimal totalCharge)
    {
        return "TOTAL=" + FormatMoneyAmount(totalCharge);
    }
}
