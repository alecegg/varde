using System.Globalization;

public static class Original
{
    public static string CreateReceipt(string parkingSessionInput)
    {
        if (parkingSessionInput == null) throw new FormatException("Input is required.");
        var trimmedParkingSessionInput = TrimInput(parkingSessionInput);
        if (trimmedParkingSessionInput.Length == 0) throw new FormatException("Input is required.");
        var parkingSessionFields = trimmedParkingSessionInput.Split(',');
        if (parkingSessionFields.Length != 3) throw new FormatException("Expected three fields.");
        var normalizedVehicleClass = ToLowerInvariant(TrimInput(parkingSessionFields[0]));
        var parkingHoursText = TrimInput(parkingSessionFields[1]);
        var normalizedValidationText = ToLowerInvariant(TrimInput(parkingSessionFields[2]));
        int parkingHours;
        if (!TryParseInteger(parkingHoursText, out parkingHours)) throw new FormatException("Hours must be an integer.");
        if (parkingHours < 1 || parkingHours > 168) throw new FormatException("Hours are outside the allowed range.");
        bool isValidated;
        if (normalizedValidationText == "true") isValidated = true;
        else if (normalizedValidationText == "false") isValidated = false;
        else throw new FormatException("Validation must be true or false.");
        decimal hourlyRate;
        if (normalizedVehicleClass == "car") hourlyRate = 5m;
        else if (normalizedVehicleClass == "motorcycle") hourlyRate = 3m;
        else if (normalizedVehicleClass == "van") hourlyRate = 8m;
        else throw new FormatException("Unknown vehicle class.");

        decimal totalBeforeDiscountAndTax = 0m;
        int unpricedParkingHours = parkingHours;
        while (unpricedParkingHours > 0)
        {
            int hoursInCurrentBlock = unpricedParkingHours > 24 ? 24 : unpricedParkingHours;
            decimal currentBlockCharge = 0m;
            for (int hourWithinCurrentBlock = 1; hourWithinCurrentBlock <= hoursInCurrentBlock; hourWithinCurrentBlock++)
            {
                if (hourWithinCurrentBlock <= 2) currentBlockCharge += hourlyRate;
                else if (hourWithinCurrentBlock <= 5) currentBlockCharge += hourlyRate * 1.5m;
                else currentBlockCharge += hourlyRate * 2m;
            }
            decimal maximumChargeForCurrentBlock = hourlyRate * 24m;
            if (currentBlockCharge > maximumChargeForCurrentBlock) currentBlockCharge = maximumChargeForCurrentBlock;
            totalBeforeDiscountAndTax += currentBlockCharge;
            unpricedParkingHours -= hoursInCurrentBlock;
        }
        if (isValidated) totalBeforeDiscountAndTax = totalBeforeDiscountAndTax * 0.90m;
        totalBeforeDiscountAndTax = totalBeforeDiscountAndTax + totalBeforeDiscountAndTax * 0.08m;
        totalBeforeDiscountAndTax = Math.Round(totalBeforeDiscountAndTax, 2, MidpointRounding.AwayFromZero);
        var formattedTotal = FormatCurrencyAmount(totalBeforeDiscountAndTax);
        var formattedValidation = FormatValidationBoolean(isValidated);
        return "Vehicle: " + normalizedVehicleClass + "\nHours: " + parkingHours.ToString(CultureInfo.InvariantCulture) + "\nValidated: " + formattedValidation + "\nTotal: $" + formattedTotal;
    }

    private static string TrimInput(string inputText)
    {
        return inputText.Trim();
    }

    private static string ToLowerInvariant(string inputText)
    {
        return inputText.ToLowerInvariant();
    }

    private static bool TryParseInteger(string integerText, out int parsedInteger)
    {
        return int.TryParse(integerText, NumberStyles.Integer, CultureInfo.InvariantCulture, out parsedInteger);
    }

    private static string FormatCurrencyAmount(decimal currencyAmount)
    {
        return currencyAmount.ToString("F2", CultureInfo.InvariantCulture);
    }

    private static string FormatValidationBoolean(bool isValidated)
    {
        if (isValidated) return "true";
        return "false";
    }

    public static string CreateReport(IEnumerable<string> parkingSessionInputs)
    {
        if (parkingSessionInputs == null) throw new ArgumentNullException(nameof(parkingSessionInputs));
        var formattedReceipts = new List<string>();
        foreach (var parkingSessionInput in parkingSessionInputs)
        {
            if (parkingSessionInput == null || parkingSessionInput.Trim().Length == 0) continue;
            formattedReceipts.Add(CreateReceipt(parkingSessionInput));
        }
        return string.Join("\n", formattedReceipts);
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        if (hours < 1 || hours > 168) throw new ArgumentOutOfRangeException(nameof(hours));
        var normalizedVehicleClass = vehicleClass == null ? "" : vehicleClass.Trim().ToLowerInvariant();
        decimal hourlyRate;
        if (normalizedVehicleClass == "car") hourlyRate = 5m;
        else if (normalizedVehicleClass == "motorcycle") hourlyRate = 3m;
        else if (normalizedVehicleClass == "van") hourlyRate = 8m;
        else throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
        var totalBeforeDiscountAndTax = 0m;
        var unpricedParkingHours = hours;
        while (unpricedParkingHours > 0)
        {
            var hoursInCurrentBlock = Math.Min(24, unpricedParkingHours);
            decimal currentBlockCharge = 0m;
            if (hoursInCurrentBlock <= 2)
            {
                currentBlockCharge = hoursInCurrentBlock * hourlyRate;
            }
            else
            {
                if (hoursInCurrentBlock > 5)
                {
                    currentBlockCharge = 2m * hourlyRate + 3m * hourlyRate * 1.5m + (hoursInCurrentBlock - 5) * hourlyRate * 2m;
                }
                else
                {
                    currentBlockCharge = 2m * hourlyRate + (hoursInCurrentBlock - 2) * hourlyRate * 1.5m;
                }
            }
            if (currentBlockCharge > hourlyRate * 24m) currentBlockCharge = hourlyRate * 24m;
            totalBeforeDiscountAndTax += currentBlockCharge;
            unpricedParkingHours -= hoursInCurrentBlock;
        }
        if (validated) totalBeforeDiscountAndTax *= 0.9m;
        totalBeforeDiscountAndTax *= 1.08m;
        return Math.Round(totalBeforeDiscountAndTax, 2, MidpointRounding.AwayFromZero);
    }
}
