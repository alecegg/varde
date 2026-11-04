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

struct Costs {
    std::int64_t points;
    std::int64_t freight;
    std::int64_t threshold;
};

const Coupon kNoCoupon{false, false, false, 0};

std::size_t head(const std::string& text) {
    std::size_t i = 0;
    while (i < text.size() && std::isspace(static_cast<unsigned char>(text[i])) != 0) {
        i += 1;
    }
    return i;
}

std::size_t tail(const std::string& text, std::size_t first) {
    std::size_t last = text.size();
    while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1])) != 0) {
        last -= 1;
    }
    return last;
}

std::string trim(const std::string& text) {
    const std::size_t first = head(text);
    return text.substr(first, tail(text, first) - first);
}

std::string up(const std::string& text) {
    std::string raised = text;
    for (char& letter : raised) {
        if (letter >= 'a' && letter <= 'z') {
            letter = static_cast<char>(letter - 'a' + 'A');
        }
    }
    return raised;
}

std::string low(std::string text) {
    for (char& letter : text) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return text;
}

bool amountDigits(const std::string& text) {
    if (text.empty() || text[0] == '0') { return false; }
    for (const char letter : text) {
        if (letter < '0' || letter > '9') { return false; }
    }
    return true;
}

bool accumulate(const std::string& text, std::int64_t maximum, std::int64_t& amount) {
    std::int64_t total = 0;
    for (const char letter : text) {
        total = total * 10 + (letter - '0');
        if (total > maximum) { return false; }
    }
    amount = total;
    return true;
}

std::int64_t couponLimit(bool percent) {
    return percent ? 50 : 500;
}

bool couponAmount(const std::string& suffix, std::int64_t maximum, std::int64_t& amount) {
    if (!amountDigits(suffix)) { return false; }
    return accumulate(suffix, maximum, amount);
}

Coupon freeOf(const std::string& coupon) {
    return Coupon{true, false, coupon == "FREESHIP", 0};
}

bool pct(const std::string& coupon) {
    return coupon.compare(0, 3, "PCT") == 0;
}

std::size_t startOf(const std::string& coupon) {
    return pct(coupon) ? 3 : 5;
}

bool marked(const std::string& coupon) {
    return coupon.compare(0, startOf(coupon), pct(coupon) ? "PCT" : "FIXED") == 0;
}

Coupon parsed(const std::string& coupon) {
    const bool percent = pct(coupon);
    std::int64_t amount = 0;
    const bool ok = couponAmount(coupon.substr(startOf(coupon)), couponLimit(percent), amount);
    if (!ok) { return kNoCoupon; }
    return Coupon{true, percent, false, amount};
}

Coupon checked(const std::string& coupon) {
    if (!marked(coupon)) { return kNoCoupon; }
    return parsed(coupon);
}

Coupon readCoupon(const std::string& coupon) {
    if (coupon.empty() || coupon == "FREESHIP") { return freeOf(coupon); }
    return checked(coupon);
}

Coupon couponOf(const std::string& coupon) {
    return readCoupon(coupon);
}

RawItem normalItem(const RawItem& item) {
    return RawItem{up(trim(item.sku)), item.qty, item.price}; }

std::vector<RawItem> normalItems(const std::vector<RawItem>& items) {
    std::vector<RawItem> out;
    for (const RawItem& item : items) {
        out.push_back(normalItem(item));
    }
    return out;
}

Normalised normalise(const Request& request) {
    Normalised normal;
    normal.tier = low(trim(request.tier));
    normal.coupon = couponOf(up(trim(request.coupon)));
    normal.region = up(trim(request.region));
    normal.items = normalItems(request.items);
    return normal;
}

bool skuChar(char letter) {
    const bool upper = letter >= 'A' && letter <= 'Z';
    const bool digit = letter >= '0' && letter <= '9';
    return upper || digit || letter == '-';
}

bool validSku(const std::string& sku) {
    if (sku.size() < 3 || sku.size() > 12) { return false; }
    for (const char letter : sku) {
        if (!skuChar(letter)) { return false; }
    }
    return true;
}

bool priceDot(bool& point) {
    if (point) { return false; }
    point = true;
    return true;
}

bool priceDigit(char letter, bool point, std::size_t& whole, std::size_t& fraction) {
    if (letter < '0' || letter > '9') { return false; }
    if (point) { fraction += 1; } else { whole += 1; }
    return true;
}

bool priceMark(char letter, bool& point, std::size_t& whole, std::size_t& fraction) {
    return letter == '.' ? priceDot(point) : priceDigit(letter, point, whole, fraction);
}

bool priceCounts(std::size_t whole, std::size_t fraction, bool point) {
    if (whole < 1 || whole > 6 || fraction > 2) { return false; }
    return !point || fraction > 0;
}

bool priceShape(const std::string& text) {
    bool point = false;
    std::size_t whole = 0;
    std::size_t fraction = 0;
    for (const char letter : text) {
        if (!priceMark(letter, point, whole, fraction)) { return false; }
    }
    return priceCounts(whole, fraction, point);
}

std::string wholeOf(const std::string& text) {
    const std::size_t point = text.find('.');
    return point == std::string::npos ? text : text.substr(0, point);
}

std::string fractionOf(const std::string& text) {
    const std::size_t point = text.find('.');
    return point == std::string::npos ? "" : text.substr(point + 1);
}

std::int64_t scaled(const std::string& fraction) {
    const std::int64_t tail = fraction.empty() ? 0 : std::stoll(fraction);
    return tail * (fraction.size() == 1 ? 10 : 1);
}

std::int64_t centsParts(const std::string& whole, const std::string& fraction) {
    return std::stoll(whole) * 100 + scaled(fraction);
}

std::int64_t centsOf(const std::string& text) {
    return centsParts(wholeOf(text), fractionOf(text)); }

void checkSku(const RawItem& item, std::int64_t index) {
    if (!validSku(item.sku)) {
        throw Rejection{QuoteError{"BAD_SKU", true, index}};
    }
}

void checkQty(std::int64_t qty, std::int64_t index) {
    if (qty < 1 || qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
}

std::int64_t checkPrice(const RawItem& item, std::int64_t index) {
    if (!priceShape(item.price)) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    const std::int64_t cents = centsOf(item.price);
    if (cents <= 0) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    return cents; }

CheckedItem validateItem(const RawItem& item, std::int64_t index) {
    checkSku(item, index);
    checkQty(item.qty, index);
    return CheckedItem{item.sku, item.qty, checkPrice(item, index)};
}

void limitItems(const std::vector<RawItem>& items) {
    if (items.empty()) {
        throw Rejection{QuoteError{"EMPTY_ORDER", false, 0}};
    }
    if (items.size() > 50) {
        throw Rejection{QuoteError{"TOO_MANY_ITEMS", false, 0}};
    }
}

std::vector<CheckedItem> checkRows(const std::vector<RawItem>& items) {
    std::vector<CheckedItem> checked;
    for (std::size_t index = 0; index < items.size(); index += 1) {
        checked.push_back(validateItem(items[index], static_cast<std::int64_t>(index)));
    }
    return checked;
}

std::vector<CheckedItem> validate(const std::vector<RawItem>& items) {
    limitItems(items);
    return checkRows(items);
}

void mergeQty(Amount& amount, const CheckedItem& item, std::int64_t index) {
    amount.qty += item.qty;
    if (amount.qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
}

void mergeExisting(const CheckedItem& item, std::int64_t index, Merged::iterator found) {
    if (found->second.cents != item.cents) {
        throw Rejection{QuoteError{"PRICE_CONFLICT", true, index}};
    }
    mergeQty(found->second, item, index);
}

void mergeOne(Merged& merged, const CheckedItem& item, std::int64_t index) {
    const auto found = merged.find(item.sku);
    if (found == merged.end()) { merged[item.sku] = Amount{item.qty, item.cents}; return; }
    mergeExisting(item, index, found);
}

bool knownTier(const std::string& tier) {
    return tier == "basic" || tier == "silver" || tier == "gold";
}

bool knownRegion(const std::string& region) {
    return region == "EU" || region == "US" || region == "ASIA";
}

void checkTier(const Normalised& request) {
    if (!knownTier(request.tier)) {
        throw Rejection{QuoteError{"BAD_TIER", false, 0}};
    }
}

void checkCoupon(const Normalised& request) {
    if (!request.coupon.valid) {
        throw Rejection{QuoteError{"BAD_COUPON", false, 0}};
    }
}

void checkRegion(const Normalised& request) {
    if (!knownRegion(request.region)) {
        throw Rejection{QuoteError{"BAD_REGION", false, 0}};
    }
}

void validateOptions(const Normalised& request) {
    checkTier(request);
    checkCoupon(request);
    checkRegion(request);
}

Merged mergeAll(const std::vector<CheckedItem>& items, const Normalised& request) {
    Merged merged;
    std::int64_t index = 0;
    for (const CheckedItem& item : items) {
        mergeOne(merged, item, index);
        index += 1;
    }
    validateOptions(request);
    return merged;
}

Merged mergeItems(const std::vector<CheckedItem>& items, const Normalised& request) {
    return mergeAll(items, request);
}

Line lineOf(const std::string& sku, const Amount& amount) {
    return Line{sku, amount.qty, amount.cents, amount.qty * amount.cents};
}

Priced priceLines(const Merged& merged) {
    Priced priced;
    priced.subtotal = 0;
    for (const auto& entry : merged) {
        const Line line = lineOf(entry.first, entry.second);
        priced.lines.push_back(line);
        priced.subtotal += line.line_cents;
    }
    return priced;
}

std::int64_t couponCut(std::int64_t net, const Coupon& parsed) {
    if (parsed.amount == 0) { return 0; }
    if (parsed.percent) { return (2 * net * parsed.amount + 100) / 200; }
    const std::int64_t requested = parsed.amount * 100;
    return requested < net ? requested : net;
}

std::int64_t tierPoints(const std::string& tier) {
    if (tier == "silver") { return 500; }
    if (tier == "gold") { return 1000; }
    return 0;
}

std::int64_t tierCut(std::int64_t subtotal, const std::string& tier) {
    return (2 * subtotal * tierPoints(tier) + 10000) / 20000;
}

Adjusted adjust(const Priced& priced, const Normalised& request) {
    const std::int64_t cut = tierCut(priced.subtotal, request.tier);
    const std::int64_t after = priced.subtotal - cut;
    const std::int64_t coupon = couponCut(after, request.coupon);
    return Adjusted{priced.subtotal, cut, coupon, after - coupon};
}

void addWhen(std::vector<std::string>& out, const char* label, bool when) {
    if (when) { out.push_back(label); }
}

void addDiscounts(std::vector<std::string>& out, std::int64_t tier, std::int64_t coupon) {
    addWhen(out, "tier", tier > 0);
    addWhen(out, "coupon", coupon > 0);
}

void addCharges(std::vector<std::string>& out, std::int64_t shipping, std::int64_t tax) {
    addWhen(out, "free-shipping", shipping == 0);
    addWhen(out, "tax", tax > 0);
}

std::vector<std::string> appliedRules(std::int64_t tier, std::int64_t coupon,
                                      std::int64_t shipping, std::int64_t tax) {
    std::vector<std::string> out;
    addDiscounts(out, tier, coupon);
    addCharges(out, shipping, tax);
    return out;
}

Quote baseQuote(const std::vector<Line>& lines, const Adjusted& adjusted,
               std::int64_t shipping, std::int64_t tax) {
    return Quote{lines, adjusted.subtotal, adjusted.tier_discount, adjusted.coupon_discount,
                 shipping, tax, adjusted.net + shipping + tax, {}};
}

Outcome quoteResult(const std::vector<Line>& lines, const Adjusted& adjusted,
                    std::int64_t shipping, std::int64_t tax) {
    Quote quote = baseQuote(lines, adjusted, shipping, tax);
    quote.applied = appliedRules(adjusted.tier_discount, adjusted.coupon_discount, shipping, tax);
    return Outcome{false, QuoteError{}, quote};
}

Costs regionCosts(const std::string& region) {
    if (region == "US") { return Costs{700, 500, 7500}; }
    if (region == "ASIA") { return Costs{1000, 1200, 15000}; }
    return Costs{2000, 800, 10000};
}

std::int64_t shippingOf(const Costs& costs, std::int64_t net, bool freeShipping) {
    return freeShipping || net >= costs.threshold ? 0 : costs.freight;
}

std::int64_t taxOf(std::int64_t net, std::int64_t points) {
    return (2 * net * points + 10000) / 20000;
}

Outcome settle(const Priced& priced, const Adjusted& adjusted, const Normalised& request) {
    const Costs costs = regionCosts(request.region);
    const std::int64_t shipping = shippingOf(costs, adjusted.net, request.coupon.free_shipping);
    const std::int64_t tax = taxOf(adjusted.net, costs.points);
    return quoteResult(priced.lines, adjusted, shipping, tax);
}

Outcome finish(const Priced& priced, const Adjusted& adjusted, const Normalised& request) {
    return settle(priced, adjusted, request);
}

Outcome complete(const Merged& merged, const Normalised& normal) {
    const Priced priced = priceLines(merged);
    const Adjusted adjusted = adjust(priced, normal);
    return finish(priced, adjusted, normal);
}

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    const Normalised normal = normalise(request);
    try {
        return complete(mergeItems(validate(normal.items), normal), normal);
    } catch (const Rejection& rejection) {
        return Outcome{true, rejection.error, Quote{}};
    }
}
