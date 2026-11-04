using System.Globalization;
public static class Original
{
 public static decimal SeatPrice(string seatClass) => GetPriceForSeatClassInput(seatClass);
 public static decimal CalculateTotal(string seatClass,int quantity) => CalculateValidatedSeatTotal(seatClass,quantity);
 public static string ProcessLine(string input) => FormatBookingInputLine(input);
 public static string ProcessAll(string input) => ProcessBookingBatchInput(input);
 private static decimal GetPriceForSeatClassInput(string bookingLineText)=>ConvertCanonicalSeatPriceText(ResolveSeatClassThroughForwarder(NormalizeAndMatchSeatClass(bookingLineText)));
 private static decimal CalculateValidatedSeatTotal(string bookingLineText,int ticketQuantity)=>CalculateQuantityCheckedTotal(ApplyQuantityPricingRules(GetPriceForSeatClassInput(bookingLineText),ticketQuantity),ticketQuantity);
 private static string FormatBookingInputLine(string bookingLineText)=>ValidateAndFormatBookingLine(ProcessValidatedBookingLine(bookingLineText));
 private static string ProcessBookingBatchInput(string bookingLineText)=>ForwardBookingBatchResult(PrepareBookingBatchReports(bookingLineText));
 private static decimal ConvertCanonicalSeatPriceText(string bookingLineText)=>decimal.Parse(ConvertSeatPriceToText(bookingLineText),CultureInfo.InvariantCulture);
 private static string ResolveSeatClassThroughForwarder(string bookingLineText)=>PassCanonicalSeatClassForward(bookingLineText);
 private static string NormalizeAndMatchSeatClass(string bookingLineText)=>MatchTrimmedCanonicalSeatClass(bookingLineText);
 private static decimal CalculateQuantityCheckedTotal(decimal unitTicketPrice,int ticketQuantity)=>ApplyPriceAndQuantityValidation(unitTicketPrice,ticketQuantity);
 private static decimal ApplyQuantityPricingRules(decimal unitTicketPrice,int ticketQuantity)=>PassSeatPriceForward(unitTicketPrice,ticketQuantity);
 private static string ValidateAndFormatBookingLine(string bookingLineText)=>HandleBookingLineInput(bookingLineText);
 private static string ProcessValidatedBookingLine(string bookingLineText)=>ValidateBookingLineFields(bookingLineText);
 private static string ForwardBookingBatchResult(string bookingLineText)=>bookingLineText;
 private static string PrepareBookingBatchReports(string bookingLineText)=>ReadBookingBatchReports(bookingLineText);
 private static string TrimNullableSeatClassText(string bookingLineText)=>bookingLineText==null?"":bookingLineText.Trim();
 private static string PassCanonicalSeatClassForward(string bookingLineText)=>MatchCanonicalSeatClassName(bookingLineText);
 private static string MatchTrimmedCanonicalSeatClass(string bookingLineText)=>MatchCanonicalSeatClassName(TrimNullableSeatClassText(bookingLineText));
 private static string MatchCanonicalSeatClassName(string bookingLineText)=>bookingLineText.Equals("Standard",StringComparison.OrdinalIgnoreCase)?"Standard":bookingLineText.Equals("Premium",StringComparison.OrdinalIgnoreCase)?"Premium":bookingLineText.Equals("VIP",StringComparison.OrdinalIgnoreCase)?"VIP":"";
 private static string ConvertSeatPriceToText(string bookingLineText)=>bookingLineText=="Standard"?"50":bookingLineText=="Premium"?"90":bookingLineText=="VIP"?"140":"0";
 private static decimal ApplyPriceAndQuantityValidation(decimal unitTicketPrice,int ticketQuantity)=>unitTicketPrice==0||!IsTicketQuantityWithinBounds(ticketQuantity)?0:ValidateSeatPriceAndQuantity(unitTicketPrice,ticketQuantity);
 private static decimal PassSeatPriceForward(decimal unitTicketPrice,int ticketQuantity)=>unitTicketPrice;
 private static decimal CalculateRoundedTicketSubtotal(decimal unitTicketPrice,int ticketQuantity)=>RoundCurrencyToCents(unitTicketPrice*ticketQuantity);
 private static decimal ValidateSeatPriceAndQuantity(decimal unitTicketPrice,int ticketQuantity){decimal subtotal=CalculateRoundedTicketSubtotal(unitTicketPrice,ticketQuantity),discount=ticketQuantity>=6?RoundCurrencyToCents(subtotal*.10m):0m,discountedSubtotal=subtotal-discount,bookingFee=discountedSubtotal<=100m?5m:discountedSubtotal<=500m?10m:20m,salesTax=RoundCurrencyToCents((discountedSubtotal+bookingFee)*.08m);return RoundCurrencyToCents(discountedSubtotal+bookingFee+salesTax);}
 private static bool IsTicketQuantityWithinBounds(int ticketQuantity)=>ticketQuantity>=1&&ticketQuantity<=20;
 private static decimal RoundCurrencyToCents(decimal x)=>decimal.Round(x,2,MidpointRounding.AwayFromZero);
 private static string HandleBookingLineInput(string bookingLineText)=>ParseAndValidateBookingDetails(bookingLineText);
 private static string ValidateBookingLineFields(string bookingLineText)=>PassBookingLineThrough(bookingLineText);
 private static string HandleBookingBatchInput(string bookingLineText)=>ProcessNonemptyBookingBatch(bookingLineText);
 private static string ReadBookingBatchReports(string bookingLineText)=>ProcessNonemptyBookingBatch(bookingLineText);
 private static string ParseAndValidateBookingDetails(string bookingLineText){if(bookingLineText==null)return CreateBookingRejectionMessage("format");var bookingLineFields=bookingLineText.Split('|');if(bookingLineFields.Length!=3)return CreateBookingRejectionMessage("format");var attendeeDisplayName=TrimBookingFieldValue(bookingLineFields[0]);var canonicalSeatClass=MatchCanonicalSeatClassName(TrimBookingFieldValue(bookingLineFields[1]));if(attendeeDisplayName.Length==0)return CreateBookingRejectionMessage("name");if(canonicalSeatClass.Length==0)return CreateBookingRejectionMessage("class");if(!int.TryParse(TrimBookingFieldValue(bookingLineFields[2]),NumberStyles.Integer,CultureInfo.InvariantCulture,out int ticketQuantity)||!IsTicketQuantityWithinBounds(ticketQuantity))return CreateBookingRejectionMessage("quantity");return BuildConfirmedBookingReport(attendeeDisplayName,canonicalSeatClass,ticketQuantity);}
 private static string PassBookingLineThrough(string bookingLineText)=>bookingLineText;
 private static string ProcessNonemptyBookingBatch(string bookingLineText)=>string.IsNullOrEmpty(bookingLineText)?"":JoinBookingBatchReports(bookingLineText);
 private static string JoinBookingReportBlocks(string bookingLineText)=>string.Join("\n",ReadNonblankBookingLines(bookingLineText));
 private static string[] ReadNonblankBookingLines(string bookingLineText){var bookingReportLines=new List<string>();using var bookingLineReader=new StringReader(bookingLineText);string? currentBookingLine;while((currentBookingLine=bookingLineReader.ReadLine())!=null)if(!string.IsNullOrWhiteSpace(currentBookingLine))bookingReportLines.Add(FormatBookingInputLine(currentBookingLine));return bookingReportLines.ToArray();}
 private static string JoinBookingBatchReports(string bookingLineText)=>JoinBookingReportBlocks(bookingLineText);
 private static string CreateBookingRejectionMessage(string bookingLineText)=>"REJECTED: "+bookingLineText;
 private static string TrimBookingFieldValue(string bookingLineText)=>bookingLineText.Trim();
 private static string BuildConfirmedBookingReport(string attendeeDisplayName,string canonicalSeatClass,int ticketQuantity){decimal ticketSubtotal=RoundCurrencyToCents(decimal.Parse(ConvertSeatPriceToText(canonicalSeatClass),CultureInfo.InvariantCulture)*ticketQuantity),groupDiscount=ticketQuantity>=6?RoundCurrencyToCents(ticketSubtotal*.10m):0m,discountedSubtotal=ticketSubtotal-groupDiscount,bookingFee=discountedSubtotal<=100?5:discountedSubtotal<=500?10:20,salesTax=RoundCurrencyToCents((discountedSubtotal+bookingFee)*.08m),finalBookingTotal=RoundCurrencyToCents(discountedSubtotal+bookingFee+salesTax);return string.Join("\n",new[]{"CONFIRMED: "+attendeeDisplayName,"Tickets: "+ticketQuantity.ToString(CultureInfo.InvariantCulture)+" x "+canonicalSeatClass,FormatBookingCurrencyLine("Subtotal",ticketSubtotal),FormatBookingCurrencyLine("Discount",groupDiscount),FormatBookingCurrencyLine("Booking fee",bookingFee),FormatBookingCurrencyLine("Tax",salesTax),FormatBookingCurrencyLine("Total",finalBookingTotal)});}
 private static string FormatBookingCurrencyLine(string currentBookingLine,decimal x)=>currentBookingLine+": $"+x.ToString("0.00",CultureInfo.InvariantCulture);
}
