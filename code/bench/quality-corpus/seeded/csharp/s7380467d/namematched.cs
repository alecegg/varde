using System;
using System.Globalization;

public static class Original
{
    public sealed record Quote(decimal Base, decimal Zone, decimal Fuel, decimal Insurance, decimal Tax, decimal Total);

    public static Quote QuoteLine(string parcelInputLineText) => RouteValidatedParcelQuoteRequest(parcelInputLineText);
    public static string BuildReport(string parcelReportInputText) => RouteParcelReportRequest(parcelReportInputText);
    private static Quote RouteValidatedParcelQuoteRequest(string parcelReportInputText) => ReceiveParcelQuoteInputLine(parcelReportInputText);
    private static Quote ReceiveParcelQuoteInputLine(string parcelReportInputText) => ConvertParcelLineIntoQuote(parcelReportInputText);
    private static Quote ConvertParcelLineIntoQuote(string parcelReportInputText) => CalculateParcelShippingQuote(SeparateParcelInputFields(parcelReportInputText));
    private static string[] SeparateParcelInputFields(string parcelReportInputText) => SplitParcelInputIntoFields(parcelReportInputText);
    private static string[] SplitParcelInputIntoFields(string parcelReportInputText) => RequireExactlyThreeParcelFields(parcelReportInputText);
    private static string[] RequireExactlyThreeParcelFields(string parcelReportInputText)
    {
        if (parcelReportInputText == null) throw new ArgumentException("Invalid input");
        var parsedParcelFields = parcelReportInputText.Split(',');
        if (parsedParcelFields.Length != 3) throw new ArgumentException("Invalid input");
        return parsedParcelFields;
    }
    private static Quote CalculateParcelShippingQuote(string[] parsedParcelFields) => DetermineParcelQuoteCharges(ValidateParsedParcelFields(parsedParcelFields));
    private static ValidatedParcelRequest ValidateParsedParcelFields(string[] parsedParcelFields) => ParseParcelWeightDestinationAndValue(parsedParcelFields);
    private static ValidatedParcelRequest ParseParcelWeightDestinationAndValue(string[] parsedParcelFields)
    {
        var parcelWeightText = TrimParcelInputField(parsedParcelFields, 0);
        var parcelDestinationCode = TrimParcelInputField(parsedParcelFields, 1).ToUpperInvariant();
        var declaredParcelValueText = TrimParcelInputField(parsedParcelFields, 2);
        if (!decimal.TryParse(parcelWeightText, NumberStyles.Number, CultureInfo.InvariantCulture, out var parcelWeightInKilograms)) throw new ArgumentException("Invalid parcelWeightInKilograms");
        if (!decimal.TryParse(declaredParcelValueText, NumberStyles.Number, CultureInfo.InvariantCulture, out var declaredParcelValue)) throw new ArgumentException("Invalid value");
        return RequireSupportedParcelRanges(parcelWeightInKilograms, parcelDestinationCode, declaredParcelValue);
    }
    private static string TrimParcelInputField(string[] parsedParcelFields, int index) => parsedParcelFields[index].Trim();
    private static ValidatedParcelRequest RequireSupportedParcelRanges(decimal parcelWeightInKilograms, string parcelDestinationCode, decimal declaredParcelValue)
    {
        if (parcelWeightInKilograms <= 0 || parcelWeightInKilograms > 30 || declaredParcelValue < 0) throw new ArgumentException("Out of range");
        return CreateValidatedParcelRequest(parcelWeightInKilograms, parcelDestinationCode, declaredParcelValue);
    }
    private static ValidatedParcelRequest CreateValidatedParcelRequest(decimal parcelWeightInKilograms, string parcelDestinationCode, decimal declaredParcelValue) => new(parcelWeightInKilograms, parcelDestinationCode, declaredParcelValue);
    private sealed record ValidatedParcelRequest(decimal Weight, string Zone, decimal Value);
    private static Quote DetermineParcelQuoteCharges(ValidatedParcelRequest parcel) => CalculateParcelQuoteComponents(parcel);
    private static Quote CalculateParcelQuoteComponents(ValidatedParcelRequest parcel) => IncludeFuelAndInsuranceComponents(parcel, ParcelRateComponents(parcel));
    private static ParcelRateComponentsResult ParcelRateComponents(ValidatedParcelRequest parcel) => new(DetermineParcelBaseShippingRate(parcel.Weight), DetermineDestinationZoneSurcharge(parcel.Zone));
    private sealed record ParcelRateComponentsResult(decimal Base, decimal Zone);
    private static decimal DetermineParcelBaseShippingRate(decimal parcelWeightInKilograms) => DetermineBaseRateForLowestWeightTier(parcelWeightInKilograms);
    private static decimal DetermineBaseRateForLowestWeightTier(decimal parcelWeightInKilograms)
    {
        if (parcelWeightInKilograms <= 1) return 5m;
        return DetermineBaseRateForMiddleWeightTiers(parcelWeightInKilograms);
    }
    private static decimal DetermineBaseRateForMiddleWeightTiers(decimal parcelWeightInKilograms)
    {
        if (parcelWeightInKilograms <= 5) return 8m;
        return DetermineBaseRateForHighestWeightTiers(parcelWeightInKilograms);
    }
    private static decimal DetermineBaseRateForHighestWeightTiers(decimal parcelWeightInKilograms)
    {
        if (parcelWeightInKilograms <= 10) return 12m;
        return 20m;
    }
    private static decimal DetermineDestinationZoneSurcharge(string parcelDestinationCode) => CheckForLocalDestinationSurcharge(parcelDestinationCode);
    private static decimal CheckForLocalDestinationSurcharge(string parcelDestinationCode)
    {
        if (parcelDestinationCode == "LOCAL") return 0m;
        return CheckForDomesticDestinationSurcharge(parcelDestinationCode);
    }
    private static decimal CheckForDomesticDestinationSurcharge(string parcelDestinationCode)
    {
        if (parcelDestinationCode == "DOMESTIC") return 4m;
        return RequireInternationalDestinationSurcharge(parcelDestinationCode);
    }
    private static decimal RequireInternationalDestinationSurcharge(string parcelDestinationCode)
    {
        if (parcelDestinationCode == "INTERNATIONAL") return 15m;
        throw new ArgumentException("Invalid destination");
    }
    private static Quote IncludeFuelAndInsuranceComponents(ValidatedParcelRequest parcel, ParcelRateComponentsResult parcelShippingRateComponents) => CreateQuoteWithInsuranceComponent(parcel, parcelShippingRateComponents, CalculateRoundedFuelSurcharge(parcelShippingRateComponents));
    private static decimal CalculateRoundedFuelSurcharge(ParcelRateComponentsResult parcelShippingRateComponents) => RoundCurrencyComponentToCents((parcelShippingRateComponents.Base + parcelShippingRateComponents.Zone) * .10m);
    private static Quote CreateQuoteWithInsuranceComponent(ValidatedParcelRequest parcel, ParcelRateComponentsResult parcelShippingRateComponents, decimal roundedParcelFuelSurcharge) => CalculateQuoteBeforeTax(parcel, parcelShippingRateComponents, roundedParcelFuelSurcharge);
    private static Quote CalculateQuoteBeforeTax(ValidatedParcelRequest parcel, ParcelRateComponentsResult parcelShippingRateComponents, decimal roundedParcelFuelSurcharge)
    {
        var roundedParcelInsurancePremium = CalculateCappedInsurancePremium(parcel.Value);
        return CalculateTaxableParcelSubtotal(parcelShippingRateComponents, roundedParcelFuelSurcharge, roundedParcelInsurancePremium);
    }
    private static decimal CalculateCappedInsurancePremium(decimal declaredParcelValue) => RoundCurrencyComponentToCents(Math.Min(declaredParcelValue * .01m, 50m));
    private static Quote CalculateTaxableParcelSubtotal(ParcelRateComponentsResult parcelShippingRateComponents, decimal roundedParcelFuelSurcharge, decimal roundedParcelInsurancePremium)
    {
        var roundedParcelTaxableSubtotal = RoundCurrencyComponentToCents(parcelShippingRateComponents.Base + parcelShippingRateComponents.Zone + roundedParcelFuelSurcharge + roundedParcelInsurancePremium);
        return ApplyTaxToParcelSubtotal(parcelShippingRateComponents, roundedParcelFuelSurcharge, roundedParcelInsurancePremium, roundedParcelTaxableSubtotal);
    }
    private static Quote ApplyTaxToParcelSubtotal(ParcelRateComponentsResult parcelShippingRateComponents, decimal roundedParcelFuelSurcharge, decimal roundedParcelInsurancePremium, decimal roundedParcelTaxableSubtotal) => CreateFullyRoundedParcelQuote(parcelShippingRateComponents, roundedParcelFuelSurcharge, roundedParcelInsurancePremium, RoundCurrencyComponentToCents(roundedParcelTaxableSubtotal * .08m));
    private static Quote CreateFullyRoundedParcelQuote(ParcelRateComponentsResult parcelShippingRateComponents, decimal roundedParcelFuelSurcharge, decimal roundedParcelInsurancePremium, decimal roundedParcelTaxAmount) =>
        new(RoundCurrencyComponentToCents(parcelShippingRateComponents.Base), RoundCurrencyComponentToCents(parcelShippingRateComponents.Zone), roundedParcelFuelSurcharge, roundedParcelInsurancePremium, roundedParcelTaxAmount, RoundCurrencyComponentToCents(parcelShippingRateComponents.Base + parcelShippingRateComponents.Zone + roundedParcelFuelSurcharge + roundedParcelInsurancePremium + roundedParcelTaxAmount));
    private static decimal RoundCurrencyComponentToCents(decimal declaredParcelValue) => Math.Round(declaredParcelValue, 2, MidpointRounding.ToEven);
    private static string RouteParcelReportRequest(string parcelReportInputText) => BuildReportFromNonblankParcelLines(parcelReportInputText);
    private static string BuildReportFromNonblankParcelLines(string parcelReportInputText)
    {
        if (parcelReportInputText == null) throw new ArgumentException("Invalid input");
        var splitReportInputLines = parcelReportInputText.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var formattedParcelReportLines = new System.Collections.Generic.List<string>();
        foreach (var parcelInputLine in splitReportInputLines) AppendFormattedQuoteForParcelLine(formattedParcelReportLines, parcelInputLine);
        return string.Join("\n", formattedParcelReportLines);
    }
    private static void AppendFormattedQuoteForParcelLine(System.Collections.Generic.List<string> formattedParcelReportLines, string parcelInputLine)
    {
        if (string.IsNullOrWhiteSpace(parcelInputLine)) return;
        formattedParcelReportLines.Add(FormatNumberedParcelQuoteLine(formattedParcelReportLines.Count + 1, QuoteLine(parcelInputLine)));
    }
    private static string FormatNumberedParcelQuoteLine(int parcelSequenceNumber, Quote parcelQuoteResult) =>
        "Parcel " + parcelSequenceNumber.ToString(CultureInfo.InvariantCulture) + ": " +
        FormatNamedCurrencyComponent("BASE", parcelQuoteResult.Base) + " " + FormatNamedCurrencyComponent("ZONE", parcelQuoteResult.Zone) + " " +
        FormatNamedCurrencyComponent("FUEL", parcelQuoteResult.Fuel) + " " + FormatNamedCurrencyComponent("INSURANCE", parcelQuoteResult.Insurance) + " " +
        FormatNamedCurrencyComponent("TAX", parcelQuoteResult.Tax) + " " + FormatNamedCurrencyComponent("TOTAL", parcelQuoteResult.Total);
    private static string FormatNamedCurrencyComponent(string currencyComponentLabel, decimal declaredParcelValue) => currencyComponentLabel + "=" + FormatCurrencyAmountWithInvariantDecimals(declaredParcelValue);
    private static string FormatCurrencyAmountWithInvariantDecimals(decimal declaredParcelValue) => declaredParcelValue.ToString("0.00", CultureInfo.InvariantCulture);
}
