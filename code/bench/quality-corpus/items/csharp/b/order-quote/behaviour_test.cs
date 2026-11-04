using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;

Solution.Item Item(string sku, int qty, string price) => new(sku, qty, price);
Solution.Request Request(
    IEnumerable<Solution.Item> items,
    string tier = "basic",
    string coupon = "",
    string region = "EU") => new(items.ToArray(), tier, coupon, region);

Solution.Line Line(string sku, int qty, long unit, long total) => new(sku, qty, unit, total);

Solution.Quote Quote(
    IEnumerable<Solution.Line> lines,
    long subtotal,
    long tier,
    long coupon,
    long shipping,
    long tax,
    long total,
    params string[] applied) => new(
        lines.ToArray(), subtotal, tier, coupon, shipping, tax, total, applied);

Solution.QuoteError Error(string code, int? index) => new(code, index);

long HalfUp(BigInteger numerator, BigInteger denominator)
{
    BigInteger quotient = BigInteger.DivRem(numerator, denominator, out BigInteger remainder);
    return (long)(quotient + (remainder * 2 >= denominator ? 1 : 0));
}

long? PriceCents(string text)
{
    if (!System.Text.RegularExpressions.Regex.IsMatch(text, @"^[0-9]{1,6}(\.[0-9]{1,2})?$"))
    {
        return null;
    }
    string[] pieces = text.Split('.');
    string fraction = pieces.Length == 1 ? "" : pieces[1];
    long cents = long.Parse(pieces[0]) * 100 + long.Parse((fraction + "00")[..2]);
    return cents > 0 ? cents : null;
}

Solution.Outcome Oracle(Solution.Request input)
{
    if (input.Items.Length == 0) return Error("EMPTY_ORDER", null);
    if (input.Items.Length > 50) return Error("TOO_MANY_ITEMS", null);
    var checkedItems = new List<(string Sku, int Qty, long Cents)>();
    for (int index = 0; index < input.Items.Length; index++)
    {
        Solution.Item row = input.Items[index];
        string sku = row.Sku.Trim().ToUpperInvariant();
        if (!System.Text.RegularExpressions.Regex.IsMatch(sku, @"^[A-Z0-9-]{3,12}$"))
            return Error("BAD_SKU", index);
        if (row.Qty < 1 || row.Qty > 1000) return Error("BAD_QTY", index);
        long? cents = PriceCents(row.Price);
        if (cents is null) return Error("BAD_PRICE", index);
        checkedItems.Add((sku, row.Qty, cents.Value));
    }

    var merged = new Dictionary<string, (int Qty, long Cents)>(StringComparer.Ordinal);
    for (int index = 0; index < checkedItems.Count; index++)
    {
        var row = checkedItems[index];
        if (!merged.TryGetValue(row.Sku, out var old))
        {
            merged.Add(row.Sku, (row.Qty, row.Cents));
            continue;
        }
        if (old.Cents != row.Cents) return Error("PRICE_CONFLICT", index);
        int quantity = old.Qty + row.Qty;
        if (quantity > 1000) return Error("BAD_QTY", index);
        merged[row.Sku] = (quantity, old.Cents);
    }

    string tierName = input.Tier.Trim().ToLowerInvariant();
    string couponName = input.Coupon.Trim().ToUpperInvariant();
    string region = input.Region.Trim().ToUpperInvariant();
    if (tierName is not ("basic" or "silver" or "gold")) return Error("BAD_TIER", null);
    bool validCoupon = couponName == "" || couponName == "FREESHIP"
        || System.Text.RegularExpressions.Regex.IsMatch(couponName,
            @"^(PCT([1-9]|[1-4][0-9]|50)|FIXED([1-9]|[1-9][0-9]|[1-4][0-9]{2}|500))$");
    if (!validCoupon) return Error("BAD_COUPON", null);
    if (region is not ("EU" or "US" or "ASIA")) return Error("BAD_REGION", null);

    Solution.Line[] lines = merged.OrderBy(pair => pair.Key, StringComparer.Ordinal)
        .Select(pair => Line(pair.Key, pair.Value.Qty, pair.Value.Cents,
            pair.Value.Cents * pair.Value.Qty)).ToArray();
    long subtotal = lines.Sum(line => line.LineCents);
    long tierRate = tierName == "gold" ? 1000 : tierName == "silver" ? 500 : 0;
    long tierDiscount = HalfUp((BigInteger)subtotal * tierRate, 10000);
    long afterTier = subtotal - tierDiscount;
    long couponDiscount = couponName.StartsWith("PCT", StringComparison.Ordinal)
        ? HalfUp((BigInteger)afterTier * long.Parse(couponName[3..]), 100)
        : couponName.StartsWith("FIXED", StringComparison.Ordinal)
            ? Math.Min(long.Parse(couponName[5..]) * 100, afterTier) : 0;
    long net = afterTier - couponDiscount;
    (long TaxRate, long BaseShipping, long Threshold) config = region switch
    {
        "EU" => (2000, 800, 10000), "US" => (700, 500, 7500), _ => (1000, 1200, 15000)
    };
    bool free = couponName == "FREESHIP" || net >= config.Threshold;
    long shipping = free ? 0 : config.BaseShipping;
    long tax = HalfUp((BigInteger)net * config.TaxRate, 10000);
    var applied = new List<string>();
    if (tierDiscount > 0) applied.Add("tier");
    if (couponDiscount > 0) applied.Add("coupon");
    if (free) applied.Add("free-shipping");
    if (tax > 0) applied.Add("tax");
    return Quote(lines, subtotal, tierDiscount, couponDiscount, shipping, tax,
        net + shipping + tax, applied.ToArray());
}

void Check(Solution.Request input, Solution.Outcome expected)
{
    Solution.Outcome actual = Solution.solution(input);
    string actualJson = System.Text.Json.JsonSerializer.Serialize(actual, actual.GetType());
    string expectedJson = System.Text.Json.JsonSerializer.Serialize(expected, expected.GetType());
    if (actualJson != expectedJson)
    {
        throw new InvalidOperationException($"{System.Text.Json.JsonSerializer.Serialize(input)}\n"
            + $"expected {expectedJson}\nactual   {actualJson}");
    }
}

void MatchOracle(Solution.Request input) => Check(input, Oracle(input));

var worked = new (Solution.Request Input, Solution.Quote Expected)[]
{
    (Request(
        new[] { Item(" ab-12 ", 2, "10.00"), Item("CD-34", 1, "5.50") }, "Silver", "", "us"),
        Quote(
            new[] { Line("AB-12", 2, 1000, 2000), Line("CD-34", 1, 550, 550) },
            2550, 128, 0, 500, 170, 3092, "tier", "tax")),
    (Request(new[] { Item("X1X", 10, "20.00") }, "gold", "pct10", "EU"),
        Quote(
            new[] { Line("X1X", 10, 2000, 20000) },
            20000, 2000, 1800, 0, 3240, 19440, "tier", "coupon", "free-shipping", "tax")),
    (Request(new[] { Item("aaa", 3, "1.00"), Item("AAA", 4, "1") }, "basic", "FIXED5", "ASIA"),
        Quote(new[] { Line("AAA", 7, 100, 700) }, 700, 0, 500, 1200, 20, 1420, "coupon", "tax")),
    (Request(new[] { Item("ZZZ", 1, "0.01") }, "silver", " freeship ", "EU"),
        Quote(new[] { Line("ZZZ", 1, 1, 1) }, 1, 0, 0, 0, 0, 1, "free-shipping")),
    (Request(new[] { Item("RND", 1, "2.50") }, "basic", "", "US"),
        Quote(new[] { Line("RND", 1, 250, 250) }, 250, 0, 0, 500, 18, 768, "tax")),
    (Request(new[] { Item("CAP", 1, "3.00") }, "basic", "FIXED500", "US"),
        Quote(new[] { Line("CAP", 1, 300, 300) }, 300, 0, 300, 500, 0, 500, "coupon")),
};
foreach (var row in worked) { Check(row.Input, row.Expected); MatchOracle(row.Input); }

var failures = new List<(Solution.Request Input, Solution.QuoteError Expected)>
{
    (Request(Array.Empty<Solution.Item>()), Error("EMPTY_ORDER", null)),
    (Request(new[] { Item("a", 1, "1") }), Error("BAD_SKU", 0)),
    (Request(new[] { Item("ABC", 0, "1") }), Error("BAD_QTY", 0)),
    (Request(new[] { Item("ABC", 1, "1.234") }), Error("BAD_PRICE", 0)),
    (Request(new[] { Item("ABC", 1, "1"), Item("abc", 1, "2") }), Error("PRICE_CONFLICT", 1)),
    (Request(new[] { Item("ABC", 600, "1"), Item("abc", 500, "1.0") }), Error("BAD_QTY", 1)),
    (Request(new[] { Item("ABC", 500, "1"), Item("abc", 501, "1.00") }), Error("BAD_QTY", 1)),
    (Request(new[] { Item("ABC", 1000, "1"), Item("abc", 1, "1.00") }), Error("BAD_QTY", 1)),
    (Request(new[] { Item("ABC", 1, "1") }, "platinum"), Error("BAD_TIER", null)),
    (Request(new[] { Item("ABC", 1, "1") }, "platinum", "PCT0", "MARS"), Error("BAD_TIER", null)),
    (Request(new[] { Item("ABC", 1, "1") }, "basic", "PCT0"), Error("BAD_COUPON", null)),
    (Request(new[] { Item("ABC", 1, "1") }, "basic", "", "MARS"), Error("BAD_REGION", null)),
    (Request(new[] { Item("ABC", 1, "0") }), Error("BAD_PRICE", 0)),
    (Request(new[] { Item("ABC", 1, "0.00") }), Error("BAD_PRICE", 0)),
};
foreach (string sku in new[] { new string('A', 2), new string('A', 13), "AB_", "AB ", "ÄBC" })
    failures.Add((Request(new[] { Item(sku, 1, "1") }), Error("BAD_SKU", 0)));
foreach (int qty in new[] { -1, 1001 })
    failures.Add((Request(new[] { Item("ABC", qty, "1") }), Error("BAD_QTY", 0)));
foreach (string price in new[]
{
    "1.234", "abc", "", "1234567", "1000000", ".50", ".5", "1.", "+1", "-1", " 1",
    "1 ", "1 0", "1,5", "1a", "1e3"
})
    failures.Add((Request(new[] { Item("ABC", 1, price) }), Error("BAD_PRICE", 0)));
foreach (string coupon in new[]
{
    "PCT0", "PCT51", "PCT07", "FIXED0", "FIXED501", "FIXED05", "PCT", "PCTX",
    "FIXED1A", "PCT-5", "PCT5.0", "FIXED 5", "OTHER"
})
    failures.Add((Request(new[] { Item("ABC", 1, "1") }, "basic", coupon),
        Error("BAD_COUPON", null)));
failures.Add((Request(Enumerable.Repeat(Item("ABC", 1, "1"), 51), "bad"),
    Error("TOO_MANY_ITEMS", null)));
failures.Add((Request(new[]
    { Item("ABC", 1, "1"), Item("BAD", 0, "bad"), Item("BAD", 1, "1") }),
    Error("BAD_QTY", 1)));
failures.Add((Request(new[]
    { Item("ABC", 1, "1"), Item("abc", 1, "2"), Item("bad", 0, "1") }),
    Error("BAD_QTY", 2)));
failures.Add((Request(new[] { Item("ABC", 1, "1"), Item("abc", 0, "2") }), Error("BAD_QTY", 1)));
failures.Add((Request(new[] { Item("ABC", 1, "1") }, "bad", "PCT0", "MARS"),
    Error("BAD_TIER", null)));
failures.Add((Request(new[] { Item("ABC", 1, "1") }, "basic", "PCT0", "MARS"),
    Error("BAD_COUPON", null)));
failures.Add((Request(new[] { Item("ABC", 1, "1"), Item("abc", 1, "2") },
    "bad", "PCT0", "MARS"), Error("PRICE_CONFLICT", 1)));
failures.Add((Request(new[] { Item("ABC", 1, "1") }, "basic", "FREESHIPX"),
    Error("BAD_COUPON", null)));
foreach (var row in failures) { Check(row.Input, row.Expected); MatchOracle(row.Input); }

foreach (var (tier, coupon, region, cents, expectedTier, expectedCoupon, expectedTax, total)
    in new[]
{
    ("silver", "", "EU", "0.10", 1L, 0L, 2L, 811L),
    ("basic", "PCT10", "US", "0.05", 0L, 1L, 0L, 504L),
    ("basic", "", "US", "0.50", 0L, 0L, 4L, 554L),
})
{
    long unit = PriceCents(cents)!.Value;
    Check(Request(new[] { Item("TIE", 1, cents) }, tier, coupon, region),
        Quote(new[] { Line("TIE", 1, unit, unit) }, unit, expectedTier, expectedCoupon,
            region == "EU" ? 800 : 500, expectedTax, total,
            expectedTier > 0 ? new[] { "tier", "tax" }
                : expectedCoupon > 0 ? new[] { "coupon" }
                : new[] { "tax" }));
}

foreach (var (region, threshold) in new[] { ("EU", 10000), ("US", 7500), ("ASIA", 15000) })
    foreach (long amount in new[] { threshold - 1, threshold })
        MatchOracle(Request(
            new[] { Item("EDGE", 1, $"{amount / 100}.{amount % 100:00}") }, "basic", "", region));
foreach (var quantities in new[] { (500, 500), (999, 1) })
    MatchOracle(Request(new[]
        { Item("ABC", quantities.Item1, "1"), Item("abc", quantities.Item2, "1.00") }));
foreach (var (region, threshold) in new[] { ("EU", 10000), ("US", 7500), ("ASIA", 15000) })
    MatchOracle(Request(
        new[]
        {
            Item("EDGE", 1,
                $"{threshold * 112 / 100 / 100}.{threshold * 112 / 100 % 100:00}")
        }, "gold", "PCT10", region));
MatchOracle(Request(new[]
{
    Item("a1x", 1, "1"), Item("A1X", 1, "1"), Item("A-1", 1, "1"), Item("A01", 1, "1")
}));
MatchOracle(Request(
    Enumerable.Range(0, 50).Select(index => Item($"S{index:00}", index + 1, "1.25")),
    "gold", "PCT7", "ASIA"));
foreach (string price in new[] { "1.005", "1.015", "2.675", "0.05", "0.15" })
    foreach (string tier in new[] { "silver", "gold" })
        MatchOracle(Request(new[] { Item("ROUND", 1, price) }, tier, "PCT7", "EU"));
MatchOracle(Request(new[] { Item("NET", 1, "105.30") }, "silver", "PCT1", "EU"));

foreach (string tier in new[] { "basic", "silver", "gold" })
    foreach (string region in new[] { "EU", "US", "ASIA" })
        MatchOracle(Request(
            Enumerable.Range(0, 50).Select(index => Item($"S{index:00}", 1000, "999999.99")),
            tier,
            "",
            region));
MatchOracle(Request(
    Enumerable.Range(0, 50).Select(index => Item($"S{index:00}", 1000, "999999.99")),
    "gold",
    "FREESHIP",
    "EU"));
Console.WriteLine(
    $"order-quote: {worked.Length} worked examples and {failures.Count} error examples passed");

ulong state = 20261017;
ulong Next()
{
    state += 0x9E3779B97F4A7C15UL;
    ulong value = state;
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9UL;
    value = (value ^ (value >> 27)) * 0x94D049BB133111EBUL;
    return value ^ (value >> 31);
}
int Below(int limit) => (int)((Next() >> 16) % (ulong)limit);
T Pick<T>(T[] values) => values[Below(values.Length)];
string Decorate(string text)
{
    if (Below(3) == 0) text = text.ToLowerInvariant();
    if (Below(4) == 0) text = " " + text + " ";
    return text;
}
string TierName() => Decorate(Pick(new[] { "basic", "silver", "gold" }));
string RegionName() => Decorate(Pick(new[] { "EU", "US", "ASIA" }));
string CouponName()
{
    string text = Below(4) switch
    {
        1 => $"PCT{1 + Below(50)}",
        2 => $"FIXED{1 + Below(500)}",
        3 => "FREESHIP",
        _ => ""
    };
    return Decorate(text);
}
string PriceText(long cents) => $"{cents / 100}.{cents % 100:00}";
string CouponKind(string coupon)
{
    string text = coupon.Trim().ToUpperInvariant();
    if (text.Length == 0) return "empty";
    if (text.StartsWith("PCT", StringComparison.Ordinal)) return "PCT";
    if (text.StartsWith("FIXED", StringComparison.Ordinal)) return "FIXED";
    return "FREESHIP";
}
int skuCounter = 0;
string Sku()
{
    skuCounter++;
    string suffix = skuCounter.ToString();
    const string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-";
    var letters = new char[1 + Below(9 - suffix.Length)];
    for (int index = 0; index < letters.Length; index++)
    {
        char letter = alphabet[Below(alphabet.Length)];
        letters[index] = letter is >= 'A' and <= 'Z' && Below(4) == 0
            ? (char)(letter + ('a' - 'A'))
            : letter;
    }
    string sku = new string(letters) + "-" + suffix;
    return Below(3) == 0 ? " " + sku + " " : sku;
}
string Price()
{
    int width = 1 + Below(27);
    long cents = (long)(1 + (Next() & ((1UL << width) - 1)));
    if (cents > 99999999) cents = 99999999;
    if (cents % 10 == 0 && Below(3) == 0) return $"{cents / 100}.{cents % 100 / 10}";
    return PriceText(cents);
}
Solution.Request Probes()
{
    string tier = TierName();
    string coupon = CouponName();
    string region = RegionName();
    switch (Below(10))
    {
        case 0:
        {
            int first = 1 + Below(999);
            string sku = Sku();
            string price = Price();
            return Request(new[] { Item(sku, first, price), Item(sku, 1000 - first, price) },
                tier, coupon, region);
        }
        case 1:
        {
            int index = Below(3);
            string[] regions = { "EU", "US", "ASIA" };
            long[] thresholds = { 10000, 7500, 15000 };
            return Request(new[] { Item(Sku(), 1, PriceText(thresholds[index])) },
                "basic", "", Decorate(regions[index]));
        }
        case 2:
        {
            int limit = 1 + Below(500);
            long cents = 1 + Below(limit * 100 - 1);
            return Request(new[] { Item(Sku(), 1, PriceText(cents)) },
                tier, $"FIXED{limit}", region);
        }
        case 3:
        {
            string probeTier = "silver";
            long subtotal = 10 + 20L * Below(4999999);
            if (Below(2) != 0)
            {
                probeTier = "gold";
                subtotal = 5 + 10L * Below(9999999);
            }
            return Request(new[] { Item(Sku(), 1, PriceText(subtotal)) },
                probeTier, "", region);
        }
        case 4:
        {
            if (Below(2) == 0)
                return Request(new[] { Item(Sku(), 1, PriceText(50 + 100L * Below(999999))) },
                    "basic", "", "US");
            return Request(new[] { Item(Sku(), 1, PriceText(5 + 10L * Below(9999999))) },
                "basic", "", "ASIA");
        }
        case 5:
            return Request(
                Enumerable.Range(0, 50).Select(index => Item(Sku(), 1 + Below(1000), Price())),
                tier, coupon, region);
        default:
        {
            int[] ratios =
            {
                1, 3, 5, 7, 9, 11, 13, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41,
                43, 45, 47, 49
            };
            int percentage = ratios[Below(ratios.Length)];
            long subtotal = 50 + 100L * Below(999999);
            return Request(new[] { Item(Sku(), 1, PriceText(subtotal)) },
                "basic", $"PCT{percentage}", region);
        }
    }
}
Solution.Request Invalid()
{
    string tier = TierName();
    string coupon = CouponName();
    string region = RegionName();
    switch (Below(10))
    {
        case 0:
            return Request(Array.Empty<Solution.Item>(), tier, coupon, region);
        case 1:
            return Request(
                Enumerable.Range(0, 51).Select(index => Item(Sku(), 1 + Below(1000), Price())),
                tier, coupon, region);
        case 2:
            return Request(
                new[] { Item(Pick(new[] { "AB", "ABCDEFGHIJKLM", "AB_", "AB CD" }), 1, "1") },
                tier, coupon, region);
        case 3:
            return Request(
                new[] { Item(Sku(), Pick(new[] { 0, -1, 1001 }), "1") }, tier, coupon, region);
        case 4:
            return Request(
                new[] { Item(Sku(), 1, Pick(new[] { "0", "1.234", "1000000", "1." })) },
                tier, coupon, region);
        case 5:
        {
            string sku = Sku();
            return Request(new[] { Item(sku, 1, "1"), Item(sku, 1, "2") }, tier, coupon, region);
        }
        case 6:
            return Request(new[] { Item(Sku(), 1, "1") }, "platinum", coupon, region);
        case 7:
            return Request(
                new[] { Item(Sku(), 1, "1") },
                tier, Pick(new[] { "PCT51", "FIXED501", "PCT07", "PCT0", "FIXED0" }), region);
        case 8:
            return Request(new[] { Item(Sku(), 1, "1") }, tier, coupon, "MARS");
        default:
        {
            string sku = Sku();
            int first = 1 + Below(1000);
            return Request(new[] { Item(sku, first, "1"), Item(sku, 1001 - first, "1") },
                tier, coupon, region);
        }
    }
}

const int Total = 4000;
int valid = 0;
int invalid = 0;
var validTiers = new SortedSet<string>(StringComparer.Ordinal);
var validRegions = new SortedSet<string>(StringComparer.Ordinal);
var validCouponKinds = new SortedSet<string>(StringComparer.Ordinal);
var errorCodes = new SortedSet<string>(StringComparer.Ordinal);
for (int round = 0; round < Total; round++)
{
    Solution.Request given = Probes();
    if (Below(8) == 0) given = Invalid();
    Solution.Outcome want = Oracle(given);
    Check(given, want);
    if (want is Solution.Quote)
    {
        valid++;
        validTiers.Add(given.Tier.Trim().ToLowerInvariant());
        validRegions.Add(given.Region.Trim().ToUpperInvariant());
        validCouponKinds.Add(CouponKind(given.Coupon));
    }
    else
    {
        invalid++;
        errorCodes.Add(((Solution.QuoteError)want).Error);
    }
}
if (valid * 2 < Total)
    throw new InvalidOperationException($"valid request ratio below 50%: {valid}/{Total}");
if (invalid == 0) throw new InvalidOperationException("generator produced no invalid requests");
foreach (string value in new[] { "basic", "silver", "gold" })
    if (!validTiers.Contains(value))
        throw new InvalidOperationException($"tier not covered: {value}");
foreach (string value in new[] { "EU", "US", "ASIA" })
    if (!validRegions.Contains(value))
        throw new InvalidOperationException($"region not covered: {value}");
foreach (string value in new[] { "empty", "PCT", "FIXED", "FREESHIP" })
    if (!validCouponKinds.Contains(value))
        throw new InvalidOperationException($"coupon kind not covered: {value}");
foreach (string code in new[]
{
    "EMPTY_ORDER", "TOO_MANY_ITEMS", "BAD_SKU", "BAD_QTY", "BAD_PRICE", "PRICE_CONFLICT",
    "BAD_TIER", "BAD_COUPON", "BAD_REGION"
})
    if (!errorCodes.Contains(code))
        throw new InvalidOperationException($"error code not covered: {code}");
Console.WriteLine(
    $"order-quote random: {Total} requests ({valid} valid, {invalid} invalid) passed; "
    + $"tiers [{string.Join(", ", validTiers)}], regions [{string.Join(", ", validRegions)}], "
    + $"coupon kinds [{string.Join(", ", validCouponKinds)}], "
    + $"errors [{string.Join(", ", errorCodes)}]");
