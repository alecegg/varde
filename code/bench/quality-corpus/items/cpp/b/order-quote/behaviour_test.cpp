#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <initializer_list>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <string>
#include <vector>

#include "solution.cpp"

using Money = __int128;

const std::regex kSkuText("[A-Z0-9-]{3,12}");
const std::regex kPriceText("[0-9]{1,6}(\\.[0-9]{1,2})?");
const std::regex kCouponText(
    "(PCT([1-9]|[1-4][0-9]|50)|FIXED([1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)");

std::int64_t narrow(Money value, const std::string& label) {
    const Money lowest = static_cast<Money>(-9000000000000000000LL);
    const Money highest = static_cast<Money>(9000000000000000000LL);
    if (value < lowest || value > highest) {
        std::cerr << "oracle value outside int64: " << label << '\n';
        std::exit(1);
    }
    return static_cast<std::int64_t>(value);
}

Money roundHalfUp(Money numerator, Money denominator) {
    return (2 * numerator + denominator) / (2 * denominator);
}

std::string oracleTrim(const std::string& text) {
    const char* blanks = " \t\n\r\v\f";
    const std::size_t first = text.find_first_not_of(blanks);
    if (first == std::string::npos) {
        return "";
    }
    const std::size_t last = text.find_last_not_of(blanks);
    return text.substr(first, last - first + 1);
}

std::string oracleUpper(const std::string& text) {
    std::string raised;
    raised.reserve(text.size());
    for (const char byte : text) {
        raised.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(byte))));
    }
    return raised;
}

std::string oracleLower(const std::string& text) {
    std::string lowered;
    lowered.reserve(text.size());
    for (const char byte : text) {
        lowered.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(byte))));
    }
    return lowered;
}

std::int64_t oracleCents(const std::string& text) {
    const std::size_t point = text.find('.');
    const std::string whole = point == std::string::npos ? text : text.substr(0, point);
    const std::string fraction = point == std::string::npos ? "" : text.substr(point + 1);
    std::int64_t cents = std::stoll(whole) * 100;
    if (fraction.size() == 1) {
        cents += std::stoll(fraction) * 10;
    } else if (fraction.size() == 2) {
        cents += std::stoll(fraction);
    }
    return cents;
}

Outcome accepted(const Quote& quote) {
    return Outcome{false, QuoteError{}, quote};
}

Outcome rejected(const std::string& code) {
    return Outcome{true, QuoteError{code, false, 0}, Quote{}};
}

Outcome rejected(const std::string& code, std::size_t index) {
    return Outcome{true, QuoteError{code, true, static_cast<std::int64_t>(index)}, Quote{}};
}

struct OracleItem {
    std::string sku;
    std::int64_t qty;
    std::int64_t cents;
};

Outcome oracle(const Request& given) {
    if (given.items.empty()) {
        return rejected("EMPTY_ORDER");
    }
    if (given.items.size() > 50) {
        return rejected("TOO_MANY_ITEMS");
    }
    std::vector<OracleItem> checked;
    for (std::size_t index = 0; index < given.items.size(); index += 1) {
        const RawItem& raw = given.items[index];
        const std::string sku = oracleUpper(oracleTrim(raw.sku));
        if (!std::regex_match(sku, kSkuText)) {
            return rejected("BAD_SKU", index);
        }
        if (raw.qty < 1 || raw.qty > 1000) {
            return rejected("BAD_QTY", index);
        }
        if (!std::regex_match(raw.price, kPriceText)) {
            return rejected("BAD_PRICE", index);
        }
        const std::int64_t cents = oracleCents(raw.price);
        if (cents <= 0) {
            return rejected("BAD_PRICE", index);
        }
        checked.push_back(OracleItem{sku, raw.qty, cents});
    }
    std::vector<OracleItem> merged;
    for (std::size_t index = 0; index < checked.size(); index += 1) {
        const OracleItem& row = checked[index];
        std::size_t position = 0;
        while (position < merged.size() && merged[position].sku != row.sku) {
            position += 1;
        }
        if (position == merged.size()) {
            merged.push_back(row);
            continue;
        }
        if (merged[position].cents != row.cents) {
            return rejected("PRICE_CONFLICT", index);
        }
        merged[position].qty += row.qty;
        if (merged[position].qty > 1000) {
            return rejected("BAD_QTY", index);
        }
    }

    const std::string tier = oracleLower(oracleTrim(given.tier));
    const std::string coupon = oracleUpper(oracleTrim(given.coupon));
    const std::string region = oracleUpper(oracleTrim(given.region));
    if (tier != "basic" && tier != "silver" && tier != "gold") {
        return rejected("BAD_TIER");
    }
    if (!coupon.empty() && !std::regex_match(coupon, kCouponText)) {
        return rejected("BAD_COUPON");
    }
    Money tax_rate = 0;
    Money base_shipping = 0;
    Money threshold = 0;
    if (region == "EU") {
        tax_rate = 2000;
        base_shipping = 800;
        threshold = 10000;
    } else if (region == "US") {
        tax_rate = 700;
        base_shipping = 500;
        threshold = 7500;
    } else if (region == "ASIA") {
        tax_rate = 1000;
        base_shipping = 1200;
        threshold = 15000;
    } else {
        return rejected("BAD_REGION");
    }

    Money tier_rate = 0;
    if (tier == "silver") {
        tier_rate = 500;
    } else if (tier == "gold") {
        tier_rate = 1000;
    }
    std::sort(merged.begin(), merged.end(),
              [](const OracleItem& left, const OracleItem& right) {
                  return left.sku < right.sku;
              });
    std::vector<Line> lines;
    Money subtotal = 0;
    for (const OracleItem& row : merged) {
        const Money unit = row.cents;
        const Money line_total = unit * row.qty;
        lines.push_back(Line{row.sku, row.qty, narrow(unit, "unit"), narrow(line_total, "line")});
        subtotal += line_total;
    }
    const Money tier_cut = roundHalfUp(subtotal * tier_rate, 10000);
    const Money after_tier = subtotal - tier_cut;
    Money coupon_cut = 0;
    if (coupon.compare(0, 3, "PCT") == 0) {
        const Money percent = std::stoll(coupon.substr(3));
        coupon_cut = roundHalfUp(after_tier * percent, 100);
    } else if (coupon.compare(0, 5, "FIXED") == 0) {
        const Money requested = std::stoll(coupon.substr(5)) * 100;
        coupon_cut = requested < after_tier ? requested : after_tier;
    }
    const Money net = after_tier - coupon_cut;
    const bool waived = coupon == "FREESHIP" || net >= threshold;
    const Money shipping = waived ? 0 : base_shipping;
    const Money tax = roundHalfUp(net * tax_rate, 10000);
    std::vector<std::string> applied;
    if (tier_cut > 0) {
        applied.push_back("tier");
    }
    if (coupon_cut > 0) {
        applied.push_back("coupon");
    }
    if (shipping == 0) {
        applied.push_back("free-shipping");
    }
    if (tax > 0) {
        applied.push_back("tax");
    }
    Quote quote;
    quote.lines = lines;
    quote.subtotal = narrow(subtotal, "subtotal");
    quote.tier_discount = narrow(tier_cut, "tier discount");
    quote.coupon_discount = narrow(coupon_cut, "coupon discount");
    quote.shipping = narrow(shipping, "shipping");
    quote.tax = narrow(tax, "tax");
    quote.total = narrow(net + shipping + tax, "total");
    quote.applied = applied;
    return accepted(quote);
}

RawItem item(const std::string& sku, std::int64_t qty, const std::string& price) {
    return RawItem{sku, qty, price};
}

Request request(std::vector<RawItem> items, const std::string& tier = "basic",
                const std::string& coupon = "", const std::string& region = "EU") {
    return Request{items, tier, coupon, region};
}

Line line(const std::string& sku, std::int64_t qty, std::int64_t unit_cents,
          std::int64_t line_cents) {
    return Line{sku, qty, unit_cents, line_cents};
}

std::vector<std::string> words(std::initializer_list<const char*> values) {
    std::vector<std::string> listed;
    for (const char* value : values) {
        listed.push_back(value);
    }
    return listed;
}

Outcome quoteOf(std::vector<Line> lines, std::int64_t subtotal, std::int64_t tier_discount,
                std::int64_t coupon_discount, std::int64_t shipping, std::int64_t tax,
                std::int64_t total, std::initializer_list<const char*> applied) {
    Quote quote;
    quote.lines = lines;
    quote.subtotal = subtotal;
    quote.tier_discount = tier_discount;
    quote.coupon_discount = coupon_discount;
    quote.shipping = shipping;
    quote.tax = tax;
    quote.total = total;
    quote.applied = words(applied);
    return accepted(quote);
}

std::string priceText(std::int64_t cents) {
    const std::int64_t part = cents % 100;
    const std::string tail = part < 10 ? "0" + std::to_string(part) : std::to_string(part);
    return std::to_string(cents / 100) + "." + tail;
}

std::string twoDigits(std::size_t value) {
    return value < 10 ? "0" + std::to_string(value) : std::to_string(value);
}

bool sameError(const QuoteError& left, const QuoteError& right) {
    if (left.code != right.code || left.has_index != right.has_index) {
        return false;
    }
    return !left.has_index || left.index == right.index;
}

bool sameLine(const Line& left, const Line& right) {
    return left.sku == right.sku && left.qty == right.qty &&
           left.unit_cents == right.unit_cents && left.line_cents == right.line_cents;
}

bool sameQuote(const Quote& left, const Quote& right) {
    if (left.lines.size() != right.lines.size() || left.applied != right.applied) {
        return false;
    }
    for (std::size_t index = 0; index < left.lines.size(); index += 1) {
        if (!sameLine(left.lines[index], right.lines[index])) {
            return false;
        }
    }
    return left.subtotal == right.subtotal &&
           left.tier_discount == right.tier_discount &&
           left.coupon_discount == right.coupon_discount && left.shipping == right.shipping &&
           left.tax == right.tax && left.total == right.total;
}

bool sameOutcome(const Outcome& left, const Outcome& right) {
    if (left.failed != right.failed) {
        return false;
    }
    return left.failed ? sameError(left.error, right.error) : sameQuote(left.quote, right.quote);
}

std::string describe(const Request& given) {
    std::string text = "items[";
    for (std::size_t index = 0; index < given.items.size(); index += 1) {
        if (index > 0) {
            text += ", ";
        }
        text += given.items[index].sku + " x" + std::to_string(given.items[index].qty) + " @" +
                given.items[index].price;
    }
    text += "] tier=" + given.tier + " coupon=" + given.coupon + " region=" + given.region;
    return text;
}

std::string describe(const Quote& quote) {
    std::string text = "quote(lines=[";
    for (std::size_t index = 0; index < quote.lines.size(); index += 1) {
        if (index > 0) {
            text += "; ";
        }
        text += quote.lines[index].sku + " " + std::to_string(quote.lines[index].qty) + " " +
                std::to_string(quote.lines[index].unit_cents) + " " +
                std::to_string(quote.lines[index].line_cents);
    }
    text += "], subtotal=" + std::to_string(quote.subtotal) + ", tier_discount=" +
            std::to_string(quote.tier_discount) + ", coupon_discount=" +
            std::to_string(quote.coupon_discount) + ", shipping=" +
            std::to_string(quote.shipping) + ", tax=" + std::to_string(quote.tax) +
            ", total=" + std::to_string(quote.total) + ", applied=[";
    for (std::size_t index = 0; index < quote.applied.size(); index += 1) {
        if (index > 0) {
            text += ", ";
        }
        text += quote.applied[index];
    }
    return text + "])";
}

std::string describe(const Outcome& outcome) {
    if (!outcome.failed) {
        return describe(outcome.quote);
    }
    std::string text = "error(" + outcome.error.code;
    if (outcome.error.has_index) {
        text += " at " + std::to_string(outcome.error.index);
    }
    return text + ")";
}

void checkCase(const Request& given, const Outcome& wanted, const std::string& label) {
    const Outcome got = solution(given);
    if (sameOutcome(got, wanted)) {
        return;
    }
    std::cerr << label << ": expected " << describe(wanted) << " but got " << describe(got)
              << " for " << describe(given) << '\n';
    std::exit(1);
}

void checkOracle(const Request& given, const std::string& label) {
    checkCase(given, oracle(given), label);
}

struct Case {
    Request given;
    Outcome wanted;
};

void checkWorkedExamples() {
    const std::vector<Case> successes = {
        {request({item(" ab-12 ", 2, "10.00"), item("CD-34", 1, "5.50")}, "Silver", "", "us"),
         quoteOf({line("AB-12", 2, 1000, 2000), line("CD-34", 1, 550, 550)}, 2550, 128, 0, 500,
                 170, 3092, {"tier", "tax"})},
        {request({item("X1X", 10, "20.00")}, "gold", "pct10", "EU"),
         quoteOf({line("X1X", 10, 2000, 20000)}, 20000, 2000, 1800, 0, 3240, 19440,
                 {"tier", "coupon", "free-shipping", "tax"})},
        {request({item("aaa", 3, "1.00"), item("AAA", 4, "1")}, "basic", "FIXED5", "ASIA"),
         quoteOf({line("AAA", 7, 100, 700)}, 700, 0, 500, 1200, 20, 1420, {"coupon", "tax"})},
        {request({item("ZZZ", 1, "0.01")}, "silver", " freeship ", "EU"),
         quoteOf({line("ZZZ", 1, 1, 1)}, 1, 0, 0, 0, 0, 1, {"free-shipping"})},
        {request({item("RND", 1, "2.50")}, "basic", "", "US"),
         quoteOf({line("RND", 1, 250, 250)}, 250, 0, 0, 500, 18, 768, {"tax"})},
        {request({item("CAP", 1, "3.00")}, "basic", "FIXED500", "US"),
         quoteOf({line("CAP", 1, 300, 300)}, 300, 0, 300, 500, 0, 500, {"coupon"})},
    };
    for (std::size_t index = 0; index < successes.size(); index += 1) {
        checkCase(successes[index].given, successes[index].wanted,
                  "worked success " + std::to_string(index + 1));
        checkOracle(successes[index].given, "worked success oracle " + std::to_string(index + 1));
    }

    const std::vector<Case> failures = {
        {request({}), rejected("EMPTY_ORDER")},
        {request({item("a", 1, "1")}), rejected("BAD_SKU", 0)},
        {request({item("ABC", 0, "1")}), rejected("BAD_QTY", 0)},
        {request({item("ABC", 1, "1.234")}), rejected("BAD_PRICE", 0)},
        {request({item("ABC", 1, "1"), item("abc", 1, "2")}), rejected("PRICE_CONFLICT", 1)},
        {request({item("ABC", 600, "1"), item("abc", 500, "1.0")}), rejected("BAD_QTY", 1)},
        {request({item("ABC", 500, "1"), item("abc", 501, "1.00")}), rejected("BAD_QTY", 1)},
        {request({item("ABC", 1, "1")}, "platinum"), rejected("BAD_TIER")},
        {request({item("ABC", 1, "1")}, "platinum", "PCT0", "MARS"), rejected("BAD_TIER")},
        {request({item("ABC", 1, "1")}, "basic", "PCT0"), rejected("BAD_COUPON")},
        {request({item("ABC", 1, "1")}, "basic", "", "MARS"), rejected("BAD_REGION")},
        {request({item("ABC", 1, "0")}), rejected("BAD_PRICE", 0)},
        {request({item("ABC", 1, "0.00")}), rejected("BAD_PRICE", 0)},
    };
    for (std::size_t index = 0; index < failures.size(); index += 1) {
        checkCase(failures[index].given, failures[index].wanted,
                  "worked failure " + std::to_string(index + 1));
        checkOracle(failures[index].given, "worked failure oracle " + std::to_string(index + 1));
    }
}

void checkValidationBoundaries() {
    for (const char* sku : {"AB", "ABCDEFGHIJKLM", "AB_", "AB ", "\xc3\x84" "BC"}) {
        const Request given = request({item(sku, 1, "1")});
        checkCase(given, rejected("BAD_SKU", 0), std::string("sku ") + sku);
        checkOracle(given, std::string("sku oracle ") + sku);
    }
    for (const std::int64_t qty : {0, -1, 1001}) {
        const Request given = request({item("ABC", qty, "1")});
        checkCase(given, rejected("BAD_QTY", 0), "qty " + std::to_string(qty));
        checkOracle(given, "qty oracle " + std::to_string(qty));
    }
    for (const char* price :
         {"0", "0.00", "1.234", "1.2.3", "abc", "", "1234567", "1000000", ".50", ".5", "1.",
          "+1", "-1", " 1", "1 ", "1 0", "1,5", "1a", "1e3"}) {
        const Request given = request({item("ABC", 1, price)});
        checkCase(given, rejected("BAD_PRICE", 0), std::string("price ") + price);
        checkOracle(given, std::string("price oracle ") + price);
    }
    for (const char* coupon :
         {"PCT0", "PCT51", "PCT07", "FIXED0", "FIXED501", "FIXED05", "PCT", "PCTX", "FIXED1A",
          "PCT-5", "PCT5.0", "FIXED 5", "OTHER"}) {
        const Request given = request({item("ABC", 1, "1")}, "basic", coupon);
        checkCase(given, rejected("BAD_COUPON"), std::string("coupon ") + coupon);
        checkOracle(given, std::string("coupon oracle ") + coupon);
    }
    checkCase(request({item("ABC", 1, "1")}, "basic", "", "mars"), rejected("BAD_REGION"),
              "region mars");

    std::vector<RawItem> crowded;
    for (int index = 0; index < 51; index += 1) {
        crowded.push_back(item("ABC", 1, "1"));
    }
    checkCase(request(crowded, "bad"), rejected("TOO_MANY_ITEMS"), "fifty one items");

    const std::vector<Case> precedence = {
        {request({item("ABC", 1, "1"), item("BAD", 0, "bad"), item("BAD", 1, "1")}),
         rejected("BAD_QTY", 1)},
        {request({item("ABC", 1, "1"), item("abc", 1, "2"), item("bad", 0, "1")}),
         rejected("BAD_QTY", 2)},
        {request({item("ABC", 1, "1"), item("abc", 0, "2")}), rejected("BAD_QTY", 1)},
        {request({item("ABC", 1, "1")}, "bad", "PCT0", "MARS"), rejected("BAD_TIER")},
        {request({item("ABC", 1, "1")}, "basic", "PCT0", "MARS"), rejected("BAD_COUPON")},
        {request({item("ABC", 1, "1"), item("abc", 1, "2")}, "bad", "PCT0", "MARS"),
         rejected("PRICE_CONFLICT", 1)},
        {request({item("ABC", 600, "1"), item("abc", 500, "2")}), rejected("PRICE_CONFLICT", 1)},
    };
    for (std::size_t index = 0; index < precedence.size(); index += 1) {
        checkCase(precedence[index].given, precedence[index].wanted,
                  "precedence " + std::to_string(index + 1));
        checkOracle(precedence[index].given, "precedence oracle " + std::to_string(index + 1));
    }
}

void checkArithmeticBoundaries() {
    const std::vector<Case> ties = {
        {request({item("TIE", 1, "0.10")}, "silver", "", "EU"),
         quoteOf({line("TIE", 1, 10, 10)}, 10, 1, 0, 800, 2, 811, {"tier", "tax"})},
        {request({item("TIE", 1, "0.05")}, "basic", "PCT10", "US"),
         quoteOf({line("TIE", 1, 5, 5)}, 5, 0, 1, 500, 0, 504, {"coupon"})},
        {request({item("TIE", 1, "0.50")}, "basic", "", "US"),
         quoteOf({line("TIE", 1, 50, 50)}, 50, 0, 0, 500, 4, 554, {"tax"})},
        {request({item("TIE", 1, "1.50")}, "basic", "", "US"),
         quoteOf({line("TIE", 1, 150, 150)}, 150, 0, 0, 500, 11, 661, {"tax"})},
    };
    for (std::size_t index = 0; index < ties.size(); index += 1) {
        checkCase(ties[index].given, ties[index].wanted, "tie " + std::to_string(index + 1));
        checkOracle(ties[index].given, "tie oracle " + std::to_string(index + 1));
    }

    const std::vector<std::pair<std::string, std::int64_t>> areas = {
        {"EU", 10000}, {"US", 7500}, {"ASIA", 15000}};
    for (const auto& area : areas) {
        for (const std::int64_t amount : {area.second - 1, area.second}) {
            const Request given = request({item("EDGE", 1, priceText(amount))}, "basic", "",
                                         area.first);
            checkOracle(given, area.first + " shipping boundary " + std::to_string(amount));
            const Outcome got = solution(given);
            const bool free_shipping = amount >= area.second;
            if (got.failed || (got.quote.shipping == 0) != free_shipping) {
                std::cerr << area.first << " shipping threshold at " << amount
                          << " produced " << describe(got) << '\n';
                std::exit(1);
            }
        }
    }

    for (const auto& area : areas) {
        const std::int64_t subtotal = area.second * 112 / 100;
        const Request given =
            request({item("EDGE", 1, priceText(subtotal))}, "gold", "PCT10", area.first);
        const Outcome wanted = oracle(given);
        const Outcome got = solution(given);
        if (wanted.failed || got.failed || wanted.quote.subtotal < area.second ||
            wanted.quote.subtotal - wanted.quote.tier_discount < area.second ||
            wanted.quote.subtotal - wanted.quote.tier_discount -
                    wanted.quote.coupon_discount >=
                area.second ||
            wanted.quote.shipping <= 0) {
            std::cerr << area.first << " discount basis setup is wrong\n";
            std::exit(1);
        }
        checkCase(given, wanted, area.first + " shipping basis after discounts");
    }

    for (const std::int64_t shared : {500, 999}) {
        const Request given =
            request({item("ABC", shared, "1"), item("abc", 1000 - shared, "1.00")});
        checkOracle(given, "merged quantity " + std::to_string(shared) + "+" +
                               std::to_string(1000 - shared));
        const Outcome got = solution(given);
        if (got.failed || got.quote.lines.size() != 1 || got.quote.lines[0].qty != 1000) {
            std::cerr << "merged exact limit produced " << describe(got) << '\n';
            std::exit(1);
        }
    }
    checkCase(request({item("ABC", 500, "1"), item("abc", 501, "1.00")}), rejected("BAD_QTY", 1),
              "merged 500+501");
    checkCase(request({item("ABC", 1000, "1"), item("abc", 1, "1.00")}), rejected("BAD_QTY", 1),
              "merged 1000+1");
    checkOracle(request({item("ABC", 1000, "1"), item("abc", 1, "1.00")}),
                "merged overflow oracle");

    const Request unordered =
        request({item("a1x", 1, "1"), item("A1X", 1, "1"), item("A-1", 1, "1"),
                 item("A01", 1, "1")});
    const Outcome sorted = solution(unordered);
    const std::vector<std::string> wanted_order = {"A-1", "A01", "A1X"};
    if (sorted.failed || sorted.quote.lines.size() != 3) {
        std::cerr << "sorted order produced " << describe(sorted) << '\n';
        std::exit(1);
    }
    for (std::size_t index = 0; index < wanted_order.size(); index += 1) {
        if (sorted.quote.lines[index].sku != wanted_order[index]) {
            std::cerr << "sorted order " << index << " is " << sorted.quote.lines[index].sku
                      << '\n';
            std::exit(1);
        }
    }
    if (sorted.quote.lines[2].qty != 2) {
        std::cerr << "merged sorted line quantity is " << sorted.quote.lines[2].qty << '\n';
        std::exit(1);
    }
    checkOracle(unordered, "sorted order oracle");

    std::vector<RawItem> fifty;
    for (int index = 0; index < 50; index += 1) {
        fifty.push_back(
            item("S" + twoDigits(static_cast<std::size_t>(index)), index + 1, "1.25"));
    }
    const Request wide = request(fifty, "gold", "PCT7", "ASIA");
    checkOracle(wide, "fifty item order");
    const Outcome wide_got = solution(wide);
    if (wide_got.failed || wide_got.quote.lines.size() != 50) {
        std::cerr << "fifty item order produced " << describe(wide_got) << '\n';
        std::exit(1);
    }

    const std::vector<std::pair<std::string, std::string>> shapes = {
        {"basic EU", "basic"},      {"silver US", "silver"},
        {"gold FIXED500 ASIA", "gold"}, {"silver FREESHIP EU", "silver"}};
    const char* shape_coupons[] = {"", "", "FIXED500", "FREESHIP"};
    const char* shape_regions[] = {"EU", "US", "ASIA", "EU"};
    for (std::size_t shape_index = 0; shape_index < shapes.size(); shape_index += 1) {
        std::vector<RawItem> maximum;
        for (int index = 0; index < 50; index += 1) {
            maximum.push_back(item("M" + twoDigits(static_cast<std::size_t>(index)), 1000,
                                   "999999.99"));
        }
        const Request given = request(maximum, shapes[shape_index].second,
                                      shape_coupons[shape_index], shape_regions[shape_index]);
        checkOracle(given, "maximum values " + shapes[shape_index].first);
        const Outcome got = solution(given);
        if (got.failed || got.quote.lines.size() != 50 ||
            got.quote.subtotal != 4999999950000LL) {
            std::cerr << "maximum values produced " << describe(got) << '\n';
            std::exit(1);
        }
    }
}

std::uint64_t nextMixed(std::uint64_t& state) {
    state += 0x9E3779B97F4A7C15ULL;
    std::uint64_t z = state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

std::size_t pickIndex(std::uint64_t& state, std::size_t count) {
    return static_cast<std::size_t>(nextMixed(state) % count);
}

template <typename T, std::size_t N>
const T& pick(std::uint64_t& state, const T (&values)[N]) {
    return values[pickIndex(state, N)];
}

std::string couponKind(const std::string& coupon) {
    const std::string normal = oracleUpper(oracleTrim(coupon));
    if (normal.empty()) {
        return "none";
    }
    if (normal == "FREESHIP") {
        return "FREESHIP";
    }
    return normal.compare(0, 3, "PCT") == 0 ? "PCT" : "FIXED";
}

std::string signature(const Request& given) {
    std::string text;
    for (const RawItem& row : given.items) {
        text += row.sku + '\x1f' + std::to_string(row.qty) + '\x1f' + row.price + '\x1e';
    }
    return text + '\x1d' + given.tier + '\x1d' + given.coupon + '\x1d' + given.region;
}

void require(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "random diversity: " << message << '\n';
        std::exit(1);
    }
}

void printCounts(const std::string& label, const std::map<std::string, int>& counts) {
    std::cout << label << ':';
    for (const auto& entry : counts) {
        std::cout << ' ' << entry.first << '=' << entry.second;
    }
    std::cout << '\n';
}

void checkRandomCases() {
    const char* prefixes[] = {"A", "a", "B", "q-", "X-", "9", "K7", "z"};
    const std::int64_t quantities[] = {1, 2, 3, 10, 97, 500, 999, 1000};
    const std::int64_t wrong_quantities[] = {0, -1, 1001, -700};
    const char* prices[] = {"0.01", "1", "1.2", "12.34", "999999.99", "2.50", "1.50", "100"};
    const char* wrong_prices[] = {"0", "0.00", "1.234", "1.2.3", "abc", "", "1234567",
                                  "1000000", ".50", ".5", "1.", "+1", "-1", " 1", "1 ", "1 0",
                                  "1,5", "1a", "1e3"};
    const char* tiers[] = {"basic", "silver", "gold", " Silver ", "BASIC", "Gold"};
    const char* wrong_tiers[] = {"platinum", "", "goldd"};
    const char* coupons[] = {"", "PCT1", "PCT7", "PCT50", "FIXED1", "FIXED500", "FREESHIP",
                             " pct10 ", "PCT25", "FIXED100", "freeship"};
    const char* wrong_coupons[] = {"PCT0", "PCT51", "PCT07", "FIXED0", "FIXED501", "FIXED05",
                                   "PCT", "PCTX", "FIXED1A", "PCT-5", "PCT5.0", "FIXED 5",
                                   "OTHER"};
    const char* regions[] = {"EU", "US", "ASIA", " us ", "eu", "Asia"};
    const char* wrong_regions[] = {"MARS", "", "EU2"};
    const char* wrong_skus[] = {"ab", "ABCDEFGHIJKLM", "AB_", " ", "-", "A B"};

    std::uint64_t state = 20261017ULL;
    std::map<std::string, int> tiers_seen;
    std::map<std::string, int> regions_seen;
    std::map<std::string, int> kinds_seen;
    std::map<std::string, int> errors_seen;
    std::set<std::string> seen;
    int valid = 0;
    const int rounds = 4000;
    for (int round = 0; round < rounds; round += 1) {
        const std::size_t count = pickIndex(state, 56);
        const std::string prefix = pick(state, prefixes);
        std::vector<RawItem> rows;
        rows.reserve(count);
        for (std::size_t index = 0; index < count; index += 1) {
            rows.push_back(
                item(prefix + twoDigits(index), pick(state, quantities), pick(state, prices)));
        }
        std::string tier = pick(state, tiers);
        std::string coupon = pick(state, coupons);
        std::string region = pick(state, regions);
        const std::size_t fault = pickIndex(state, 100);
        if (fault < 10 && rows.size() >= 2 && rows.size() <= 50) {
            const std::size_t at = pickIndex(state, rows.size());
            const std::size_t other = (at + 1 + pickIndex(state, rows.size() - 1)) % rows.size();
            if (fault == 0) {
                rows[at].sku = pick(state, wrong_skus);
            } else if (fault == 1) {
                rows[at].qty = pick(state, wrong_quantities);
            } else if (fault == 2) {
                rows[at].price = pick(state, wrong_prices);
            } else if (fault == 3) {
                rows[at].sku = rows[other].sku;
                rows[at].price = "2";
            } else if (fault == 4) {
                rows[at].sku = rows[other].sku;
                rows[at].price = rows[other].price;
                rows[at].qty = 999;
                rows[other].qty = 999;
            } else if (fault == 5) {
                rows[at].sku = rows[other].sku;
                rows[at].price = rows[other].price;
                rows[at].qty = 500;
                rows[other].qty = 500;
            } else if (fault == 6) {
                rows[at].sku = rows[other].sku;
                rows[at].price = rows[other].price;
                rows[at].qty = 500;
                rows[other].qty = 501;
            } else if (fault == 7) {
                tier = pick(state, wrong_tiers);
            } else if (fault == 8) {
                coupon = pick(state, wrong_coupons);
            } else {
                region = pick(state, wrong_regions);
            }
        }
        const Request given = request(rows, tier, coupon, region);
        const Outcome wanted = oracle(given);
        checkCase(given, wanted, "random case " + std::to_string(round));
        seen.insert(signature(given));
        if (wanted.failed) {
            errors_seen[wanted.error.code] += 1;
        } else {
            valid += 1;
            tiers_seen[oracleLower(oracleTrim(tier))] += 1;
            regions_seen[oracleUpper(oracleTrim(region))] += 1;
            kinds_seen[couponKind(coupon)] += 1;
        }
    }

    std::cout << "random: " << rounds << " cases, " << valid << " valid, " << seen.size()
              << " distinct\n";
    printCounts("tiers", tiers_seen);
    printCounts("regions", regions_seen);
    printCounts("coupons", kinds_seen);
    printCounts("errors", errors_seen);

    require(valid * 2 >= rounds, "fewer than half of the random cases are valid");
    require(seen.size() * 2 >= static_cast<std::size_t>(rounds), "random requests are repetitive");
    for (const char* name : {"basic", "silver", "gold"}) {
        require(tiers_seen[name] > 0, std::string("tier missing: ") + name);
    }
    for (const char* name : {"EU", "US", "ASIA"}) {
        require(regions_seen[name] > 0, std::string("region missing: ") + name);
    }
    for (const char* name : {"none", "PCT", "FIXED", "FREESHIP"}) {
        require(kinds_seen[name] > 0, std::string("coupon kind missing: ") + name);
    }
    for (const char* name :
         {"EMPTY_ORDER", "TOO_MANY_ITEMS", "BAD_SKU", "BAD_QTY", "BAD_PRICE", "PRICE_CONFLICT",
          "BAD_TIER", "BAD_COUPON", "BAD_REGION"}) {
        require(errors_seen[name] > 0, std::string("error missing: ") + name);
    }
}

int main() {
    checkWorkedExamples();
    checkValidationBoundaries();
    checkArithmeticBoundaries();
    checkRandomCases();
    return 0;
}
