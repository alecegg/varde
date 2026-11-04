Implement a parcel shipping quote module with one parcel per nonblank input line.
Expose public static `Original.QuoteLine(string)` returning a quote result, or throwing `ArgumentException` for invalid input.
Input format is `weightKg,destination,declaredValue`; trim fields, parse invariant-culture decimals, and accept destination `LOCAL`, `DOMESTIC`, or `INTERNATIONAL` case-insensitively.
Weight must be greater than 0 and at most 30 kg; declared value must be 0 or greater.
Base rates per parcel: up to 1 kg = 5.00, >1 to 5 kg = 8.00, >5 to 10 kg = 12.00, >10 to 30 kg = 20.00.
Destination surcharges are LOCAL 0.00, DOMESTIC 4.00, INTERNATIONAL 15.00.
Fuel surcharge is 10% of base rate plus destination surcharge.
Insurance is 1% of declared value, capped at 50.00; tax is 8% of subtotal including insurance.
Round each monetary component to 2 decimals using midpoint-to-even; total is the rounded sum of components.
Expose `Original.QuoteLine(string)` and `Original.BuildReport(string)`; report ignores blank lines and returns one line per parcel: `Parcel N: BASE=0.00 ZONE=0.00 FUEL=0.00 INSURANCE=0.00 TAX=0.00 TOTAL=0.00`, using invariant decimals and `\n` separators.
