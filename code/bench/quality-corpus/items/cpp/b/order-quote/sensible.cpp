#include <cctype>
#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

struct RawItem {
    std::string sku;
    std::int64_t qty;
    std::string price;
};

struct Request {
    std::vector<RawItem> items;
    std::string tier;
    std::string coupon;
    std::string region;
};

struct Line {
    std::string sku;
    std::int64_t qty;
    std::int64_t unit_cents;
    std::int64_t line_cents;
};

struct Quote {
    std::vector<Line> lines;
    std::int64_t subtotal;
    std::int64_t tier_discount;
    std::int64_t coupon_discount;
    std::int64_t shipping;
    std::int64_t tax;
    std::int64_t total;
    std::vector<std::string> applied;
};

struct QuoteError {
    std::string code;
    bool has_index;
    std::int64_t index;
};

struct Outcome {
    bool failed;
    QuoteError error;
    Quote quote;
};

struct Coupon {
    bool valid;
    bool percent;
    bool free_shipping;
    std::int64_t amount;
};

struct Normalised {
    std::vector<RawItem> items;
    std::string tier;
    Coupon coupon;
    std::string region;
};

struct CheckedItem {
    std::string sku;
    std::int64_t qty;
    std::int64_t cents;
};

struct Amount {
    std::int64_t qty;
    std::int64_t cents;
};

using Merged = std::map<std::string, Amount>;

struct Priced {
    std::vector<Line> lines;
    std::int64_t subtotal;
};

struct Adjusted {
    std::int64_t subtotal;
    std::int64_t tier_discount;
    std::int64_t coupon_discount;
    std::int64_t net;
};

struct Rejection {
    QuoteError error;
};

std::string trimmed(const std::string& text) {
    std::size_t first = 0;
    while (first < text.size() &&
           std::isspace(static_cast<unsigned char>(text[first])) != 0) {
        first += 1;
    }
    std::size_t last = text.size();
    while (last > first &&
           std::isspace(static_cast<unsigned char>(text[last - 1])) != 0) {
        last -= 1;
    }
    return text.substr(first, last - first);
}

std::string upperAscii(const std::string& text) {
    std::string raised = text;
    for (char& letter : raised) {
        if (letter >= 'a' && letter <= 'z') {
            letter = static_cast<char>(letter - 'a' + 'A');
        }
    }
    return raised;
}

bool couponAmount(const std::string& suffix, std::int64_t maximum,
                  std::int64_t& amount) {
    if (suffix.empty() || suffix[0] == '0') {
        return false;
    }
    std::int64_t total = 0;
    for (const char letter : suffix) {
        if (letter < '0' || letter > '9') {
            return false;
        }
        total = total * 10 + (letter - '0');
        if (total > maximum) {
            return false;
        }
    }
    amount = total;
    return true;
}

const Coupon kNoCoupon{false, false, false, 0};

Coupon couponOf(const std::string& coupon) {
    if (coupon.empty() || coupon == "FREESHIP") {
        return Coupon{true, false, coupon == "FREESHIP", 0};
    }
    const bool percent = coupon.compare(0, 3, "PCT") == 0;
    const std::size_t start = percent ? 3 : 5;
    if (coupon.compare(0, start, percent ? "PCT" : "FIXED") != 0) {
        return kNoCoupon;
    }
    std::int64_t amount = 0;
    if (!couponAmount(coupon.substr(start), percent ? 50 : 500, amount)) {
        return kNoCoupon;
    }
    return Coupon{true, percent, false, amount};
}

Normalised normalise(const Request& request) {
    Normalised normal;
    std::string tier = trimmed(request.tier);
    for (char& letter : tier) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    normal.tier = tier;
    normal.coupon = couponOf(upperAscii(trimmed(request.coupon)));
    normal.region = upperAscii(trimmed(request.region));
    for (const RawItem& item : request.items) {
        normal.items.push_back(
            RawItem{upperAscii(trimmed(item.sku)), item.qty, item.price});
    }
    return normal;
}

bool validSku(const std::string& sku) {
    if (sku.size() < 3 || sku.size() > 12) {
        return false;
    }
    for (const char letter : sku) {
        const bool uppercase = letter >= 'A' && letter <= 'Z';
        const bool digit = letter >= '0' && letter <= '9';
        if (!uppercase && !digit && letter != '-') {
            return false;
        }
    }
    return true;
}

bool priceShape(const std::string& text) {
    bool has_point = false;
    std::size_t whole_digits = 0;
    std::size_t fraction_digits = 0;
    for (const char letter : text) {
        if (letter == '.') {
            if (has_point) {
                return false;
            }
            has_point = true;
        } else if (letter >= '0' && letter <= '9') {
            if (has_point) {
                fraction_digits += 1;
            } else {
                whole_digits += 1;
            }
        } else {
            return false;
        }
    }
    if (whole_digits < 1 || whole_digits > 6 || fraction_digits > 2) {
        return false;
    }
    return !has_point || fraction_digits > 0;
}

std::int64_t centsOf(const std::string& text) {
    const std::size_t point = text.find('.');
    const std::string whole = point == std::string::npos ? text : text.substr(0, point);
    const std::string fraction = point == std::string::npos ? "" : text.substr(point + 1);
    const std::int64_t units = std::stoll(whole);
    const std::int64_t tail = fraction.empty() ? 0 : std::stoll(fraction);
    const std::int64_t scale = fraction.size() == 1 ? 10 : 1;
    return units * 100 + tail * scale;
}

CheckedItem validateItem(const RawItem& item, std::int64_t index) {
    if (!validSku(item.sku)) {
        throw Rejection{QuoteError{"BAD_SKU", true, index}};
    }
    if (item.qty < 1 || item.qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
    if (!priceShape(item.price)) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    const std::int64_t cents = centsOf(item.price);
    if (cents <= 0) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    return CheckedItem{item.sku, item.qty, cents};
}

std::vector<CheckedItem> validate(const std::vector<RawItem>& items) {
    if (items.empty()) {
        throw Rejection{QuoteError{"EMPTY_ORDER", false, 0}};
    }
    if (items.size() > 50) {
        throw Rejection{QuoteError{"TOO_MANY_ITEMS", false, 0}};
    }
    std::vector<CheckedItem> checked;
    checked.reserve(items.size());
    for (std::size_t index = 0; index < items.size(); index += 1) {
        checked.push_back(validateItem(items[index], static_cast<std::int64_t>(index)));
    }
    return checked;
}

void mergeOne(Merged& merged, const CheckedItem& item, std::int64_t index) {
    const auto found = merged.find(item.sku);
    if (found == merged.end()) {
        merged[item.sku] = Amount{item.qty, item.cents};
        return;
    }
    if (found->second.cents != item.cents) {
        throw Rejection{QuoteError{"PRICE_CONFLICT", true, index}};
    }
    found->second.qty += item.qty;
    if (found->second.qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
}

void validateOptions(const Normalised& request) {
    const bool tier_known = request.tier == "basic" || request.tier == "silver" ||
                            request.tier == "gold";
    if (!tier_known) {
        throw Rejection{QuoteError{"BAD_TIER", false, 0}};
    }
    if (!request.coupon.valid) {
        throw Rejection{QuoteError{"BAD_COUPON", false, 0}};
    }
    const bool region_known = request.region == "EU" || request.region == "US" ||
                              request.region == "ASIA";
    if (!region_known) {
        throw Rejection{QuoteError{"BAD_REGION", false, 0}};
    }
}

Merged mergeItems(const std::vector<CheckedItem>& items, const Normalised& request) {
    Merged merged;
    std::int64_t index = 0;
    for (const CheckedItem& item : items) {
        mergeOne(merged, item, index);
        index += 1;
    }
    validateOptions(request);
    return merged;
}

Priced priceLines(const Merged& merged) {
    Priced priced;
    priced.subtotal = 0;
    for (const auto& entry : merged) {
        const std::int64_t line_cents = entry.second.qty * entry.second.cents;
        priced.lines.push_back(
            Line{entry.first, entry.second.qty, entry.second.cents, line_cents});
        priced.subtotal += line_cents;
    }
    return priced;
}

std::int64_t couponDiscount(std::int64_t net, const Coupon& parsed) {
    if (parsed.amount == 0) {
        return 0;
    }
    if (parsed.percent) {
        return (2 * net * parsed.amount + 100) / 200;
    }
    const std::int64_t requested = parsed.amount * 100;
    return requested < net ? requested : net;
}

Adjusted adjust(const Priced& priced, const Normalised& request) {
    std::int64_t basis_points = 0;
    if (request.tier == "silver") {
        basis_points = 500;
    } else if (request.tier == "gold") {
        basis_points = 1000;
    }
    const std::int64_t tier_cut = (2 * priced.subtotal * basis_points + 10000) / 20000;
    const std::int64_t after_tier = priced.subtotal - tier_cut;
    const std::int64_t coupon_cut = couponDiscount(after_tier, request.coupon);
    return Adjusted{priced.subtotal, tier_cut, coupon_cut, after_tier - coupon_cut};
}

std::vector<std::string> appliedRules(std::int64_t tier_cut, std::int64_t coupon_cut,
                                      std::int64_t shipping, std::int64_t tax) {
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
    return applied;
}

Outcome quoteResult(const std::vector<Line>& lines, const Adjusted& adjusted,
                    std::int64_t shipping, std::int64_t tax) {
    Quote quote;
    quote.lines = lines;
    quote.subtotal = adjusted.subtotal;
    quote.tier_discount = adjusted.tier_discount;
    quote.coupon_discount = adjusted.coupon_discount;
    quote.shipping = shipping;
    quote.tax = tax;
    quote.total = adjusted.net + shipping + tax;
    quote.applied =
        appliedRules(adjusted.tier_discount, adjusted.coupon_discount, shipping, tax);
    return Outcome{false, QuoteError{}, quote};
}

Outcome finish(const Priced& priced, const Adjusted& adjusted,
               const Normalised& request) {
    std::int64_t tax_points = 2000;
    std::int64_t freight = 800;
    std::int64_t threshold = 10000;
    if (request.region == "US") {
        tax_points = 700;
        freight = 500;
        threshold = 7500;
    } else if (request.region == "ASIA") {
        tax_points = 1000;
        freight = 1200;
        threshold = 15000;
    }
    const std::int64_t shipping =
        request.coupon.free_shipping || adjusted.net >= threshold ? 0 : freight;
    const std::int64_t tax = (2 * adjusted.net * tax_points + 10000) / 20000;
    return quoteResult(priced.lines, adjusted, shipping, tax);
}

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    const Normalised normal = normalise(request);
    try {
        const std::vector<CheckedItem> checked = validate(normal.items);
        const Merged merged = mergeItems(checked, normal);
        const Priced priced = priceLines(merged);
        const Adjusted adjusted = adjust(priced, normal);
        return finish(priced, adjusted, normal);
    } catch (const Rejection& rejection) {
        return Outcome{true, rejection.error, Quote{}};
    }
}
