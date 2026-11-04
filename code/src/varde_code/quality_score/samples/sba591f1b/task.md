Implement a parking garage fee module in C#; each nonblank input line describes one parking session as `vehicleClass,hours,validated`.
Expose `public static class Original` in the global namespace with `CreateReceipt(string line)`, `CreateReport(IEnumerable<string> lines)`, and `CalculateFee(string vehicleClass, int hours, bool validated)`.
Accept vehicle classes `car`, `motorcycle`, and `van` case-insensitively, with base hourly rates of $5, $3, and $8 respectively.
Hours must be an integer from 1 through 168 inclusive; validation must be exactly `true` or `false` ignoring case.
Reject null, blank, malformed, unknown-class, invalid-hour, or invalid-validation input with `FormatException` from `CreateReceipt`.
Price each 24-hour block independently: first 2 hours at base rate, hours 3-5 at 1.5×, and hours 6-24 at 2×; a partial block uses its full hours.
Cap each block's pre-discount charge at 24 times its base hourly rate; a final partial block is priced by the same hourly tiers and cap.
Apply a 10% validation discount to the capped charge, then add 8% tax; round the final fee to cents using midpoint-away-from-zero.
`CalculateFee` applies these pricing rules and throws `ArgumentOutOfRangeException` for hours outside 1-168 and `ArgumentException` for an unknown class.
`CreateReceipt` returns exactly `Vehicle: {class}\nHours: {hours}\nValidated: {true|false}\nTotal: ${amount:F2}` with normalized lowercase class and lowercase validation.
`CreateReport` skips blank lines and joins each remaining receipt with one newline; an invalid nonblank line propagates its `FormatException`.
