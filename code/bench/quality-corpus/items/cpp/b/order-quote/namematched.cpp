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

std::size_t firstNonSpace(const std::string& text) {
    std::size_t i = 0;
    while (i < text.size() && std::isspace(static_cast<unsigned char>(text[i])) != 0) {
        i += 1;
    }
    return i;
}

std::size_t lastNonSpace(const std::string& text, std::size_t first) {
    std::size_t last = text.size();
    while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1])) != 0) {
        last -= 1;
    }
    return last;
}

std::string trimmed(const std::string& text) {
    const std::size_t first = firstNonSpace(text);
    return text.substr(first, lastNonSpace(text, first) - first);
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

std::string lowerAscii(std::string text) {
    for (char& letter : text) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return text;
}

bool amountDigitText(const std::string& text) {
    if (text.empty() || text[0] == '0') { return false; }
    for (const char letter : text) {
        if (letter < '0' || letter > '9') { return false; }
    }
    return true;
}

bool accumulateAmount(const std::string& text, std::int64_t maximum, std::int64_t& amount) {
    std::int64_t total = 0;
    for (const char letter : text) {
        total = total * 10 + (letter - '0');
        if (total > maximum) { return false; }
    }
    amount = total;
    return true;
}

std::int64_t couponMaximum(bool percent) {
    return percent ? 50 : 500;
}

bool readCouponAmount(const std::string& suffix, std::int64_t maximum, std::int64_t& amount) {
    if (!amountDigitText(suffix)) { return false; }
    return accumulateAmount(suffix, maximum, amount);
}

Coupon freeCoupon(const std::string& coupon) {
    return Coupon{true, false, coupon == "FREESHIP", 0};
}

bool percentCoupon(const std::string& coupon) {
    return coupon.compare(0, 3, "PCT") == 0;
}

std::size_t couponStart(const std::string& coupon) {
    return percentCoupon(coupon) ? 3 : 5;
}

bool markedCoupon(const std::string& coupon) {
    return coupon.compare(0, couponStart(coupon), percentCoupon(coupon) ? "PCT" : "FIXED") == 0;
}

Coupon parseCoupon(const std::string& coupon) {
    const bool percent = percentCoupon(coupon);
    std::int64_t amount = 0;
    const bool ok =
        readCouponAmount(coupon.substr(couponStart(coupon)), couponMaximum(percent), amount);
    if (!ok) { return kNoCoupon; }
    return Coupon{true, percent, false, amount};
}

Coupon checkCouponText(const std::string& coupon) {
    if (!markedCoupon(coupon)) { return kNoCoupon; }
    return parseCoupon(coupon);
}

Coupon readCouponText(const std::string& coupon) {
    if (coupon.empty() || coupon == "FREESHIP") { return freeCoupon(coupon); }
    return checkCouponText(coupon);
}

Coupon couponFrom(const std::string& coupon) {
    return readCouponText(coupon);
}

RawItem normalisedItem(const RawItem& item) {
    return RawItem{upperAscii(trimmed(item.sku)), item.qty, item.price}; }

std::vector<RawItem> normalisedItems(const std::vector<RawItem>& items) {
    std::vector<RawItem> out;
    for (const RawItem& item : items) {
        out.push_back(normalisedItem(item));
    }
    return out;
}

Normalised normaliseRequest(const Request& request) {
    Normalised normal;
    normal.tier = lowerAscii(trimmed(request.tier));
    normal.coupon = couponFrom(upperAscii(trimmed(request.coupon)));
    normal.region = upperAscii(trimmed(request.region));
    normal.items = normalisedItems(request.items);
    return normal;
}

bool validSkuChar(char letter) {
    const bool upper = letter >= 'A' && letter <= 'Z';
    const bool digit = letter >= '0' && letter <= '9';
    return upper || digit || letter == '-';
}

bool validSkuText(const std::string& sku) {
    if (sku.size() < 3 || sku.size() > 12) { return false; }
    for (const char letter : sku) {
        if (!validSkuChar(letter)) { return false; }
    }
    return true;
}

bool pricePoint(bool& point) {
    if (point) { return false; }
    point = true;
    return true;
}

bool priceDigits(char letter, bool point, std::size_t& whole, std::size_t& fraction) {
    if (letter < '0' || letter > '9') { return false; }
    if (point) { fraction += 1; } else { whole += 1; }
    return true;
}

bool priceCharacter(char letter, bool& point, std::size_t& whole, std::size_t& fraction) {
    return letter == '.' ? pricePoint(point) : priceDigits(letter, point, whole, fraction);
}

bool priceDigitCounts(std::size_t whole, std::size_t fraction, bool point) {
    if (whole < 1 || whole > 6 || fraction > 2) { return false; }
    return !point || fraction > 0;
}

bool priceShapeValid(const std::string& text) {
    bool point = false;
    std::size_t whole = 0;
    std::size_t fraction = 0;
    for (const char letter : text) {
        if (!priceCharacter(letter, point, whole, fraction)) { return false; }
    }
    return priceDigitCounts(whole, fraction, point);
}

std::string wholeDigits(const std::string& text) {
    const std::size_t point = text.find('.');
    return point == std::string::npos ? text : text.substr(0, point);
}

std::string fractionDigits(const std::string& text) {
    const std::size_t point = text.find('.');
    return point == std::string::npos ? "" : text.substr(point + 1);
}

std::int64_t scaledFraction(const std::string& fraction) {
    const std::int64_t lastNonSpace = fraction.empty() ? 0 : std::stoll(fraction);
    return lastNonSpace * (fraction.size() == 1 ? 10 : 1);
}

std::int64_t priceCentsParts(const std::string& whole, const std::string& fraction) {
    return std::stoll(whole) * 100 + scaledFraction(fraction);
}

std::int64_t priceCents(const std::string& text) {
    return priceCentsParts(wholeDigits(text), fractionDigits(text)); }

void requireSku(const RawItem& item, std::int64_t index) {
    if (!validSkuText(item.sku)) {
        throw Rejection{QuoteError{"BAD_SKU", true, index}};
    }
}

void requireQuantity(std::int64_t qty, std::int64_t index) {
    if (qty < 1 || qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
}

std::int64_t requirePrice(const RawItem& item, std::int64_t index) {
    if (!priceShapeValid(item.price)) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    const std::int64_t cents = priceCents(item.price);
    if (cents <= 0) {
        throw Rejection{QuoteError{"BAD_PRICE", true, index}};
    }
    return cents; }

CheckedItem checkedItem(const RawItem& item, std::int64_t index) {
    requireSku(item, index);
    requireQuantity(item.qty, index);
    return CheckedItem{item.sku, item.qty, requirePrice(item, index)};
}

void requireItemCount(const std::vector<RawItem>& items) {
    if (items.empty()) {
        throw Rejection{QuoteError{"EMPTY_ORDER", false, 0}};
    }
    if (items.size() > 50) {
        throw Rejection{QuoteError{"TOO_MANY_ITEMS", false, 0}};
    }
}

std::vector<CheckedItem> checkedRows(const std::vector<RawItem>& items) {
    std::vector<CheckedItem> checkCouponText;
    for (std::size_t index = 0; index < items.size(); index += 1) {
        checkCouponText.push_back(checkedItem(items[index], static_cast<std::int64_t>(index)));
    }
    return checkCouponText;
}

std::vector<CheckedItem> validateItems(const std::vector<RawItem>& items) {
    requireItemCount(items);
    return checkedRows(items);
}

void mergeQuantity(Amount& amount, const CheckedItem& item, std::int64_t index) {
    amount.qty += item.qty;
    if (amount.qty > 1000) {
        throw Rejection{QuoteError{"BAD_QTY", true, index}};
    }
}

void mergeCheckedItem(const CheckedItem& item, std::int64_t index, Merged::iterator found) {
    if (found->second.cents != item.cents) {
        throw Rejection{QuoteError{"PRICE_CONFLICT", true, index}};
    }
    mergeQuantity(found->second, item, index);
}

void mergeItem(Merged& merged, const CheckedItem& item, std::int64_t index) {
    const auto found = merged.find(item.sku);
    if (found == merged.end()) { merged[item.sku] = Amount{item.qty, item.cents}; return; }
    mergeCheckedItem(item, index, found);
}

bool tierKnown(const std::string& tier) {
    return tier == "basic" || tier == "silver" || tier == "gold";
}

bool regionKnown(const std::string& region) {
    return region == "EU" || region == "US" || region == "ASIA";
}

void requireTier(const Normalised& request) {
    if (!tierKnown(request.tier)) {
        throw Rejection{QuoteError{"BAD_TIER", false, 0}};
    }
}

void requireCouponOption(const Normalised& request) {
    if (!request.coupon.valid) {
        throw Rejection{QuoteError{"BAD_COUPON", false, 0}};
    }
}

void requireRegion(const Normalised& request) {
    if (!regionKnown(request.region)) {
        throw Rejection{QuoteError{"BAD_REGION", false, 0}};
    }
}

void validateOrderOptions(const Normalised& request) {
    requireTier(request);
    requireCouponOption(request);
    requireRegion(request);
}

Merged mergeCheckedItems(const std::vector<CheckedItem>& items, const Normalised& request) {
    Merged merged;
    std::int64_t index = 0;
    for (const CheckedItem& item : items) {
        mergeItem(merged, item, index);
        index += 1;
    }
    validateOrderOptions(request);
    return merged;
}

Merged mergedItems(const std::vector<CheckedItem>& items, const Normalised& request) {
    return mergeCheckedItems(items, request);
}

Line lineFor(const std::string& sku, const Amount& amount) {
    return Line{sku, amount.qty, amount.cents, amount.qty * amount.cents};
}

Priced pricedLines(const Merged& merged) {
    Priced priced;
    priced.subtotal = 0;
    for (const auto& entry : merged) {
        const Line line = lineFor(entry.first, entry.second);
        priced.lines.push_back(line);
        priced.subtotal += line.line_cents;
    }
    return priced;
}

std::int64_t couponDiscount(std::int64_t net, const Coupon& parseCoupon) {
    if (parseCoupon.amount == 0) { return 0; }
    if (parseCoupon.percent) { return (2 * net * parseCoupon.amount + 100) / 200; }
    const std::int64_t requested = parseCoupon.amount * 100;
    return requested < net ? requested : net;
}

std::int64_t tierBasisPoints(const std::string& tier) {
    if (tier == "silver") { return 500; }
    if (tier == "gold") { return 1000; }
    return 0;
}

std::int64_t tierDiscount(std::int64_t subtotal, const std::string& tier) {
    return (2 * subtotal * tierBasisPoints(tier) + 10000) / 20000;
}

Adjusted adjustSubtotal(const Priced& priced, const Normalised& request) {
    const std::int64_t cut = tierDiscount(priced.subtotal, request.tier);
    const std::int64_t after = priced.subtotal - cut;
    const std::int64_t coupon = couponDiscount(after, request.coupon);
    return Adjusted{priced.subtotal, cut, coupon, after - coupon};
}

void addAppliedWhen(std::vector<std::string>& out, const char* label, bool when) {
    if (when) { out.push_back(label); }
}

void addDiscountRules(std::vector<std::string>& out, std::int64_t tier, std::int64_t coupon) {
    addAppliedWhen(out, "tier", tier > 0);
    addAppliedWhen(out, "coupon", coupon > 0);
}

void addChargeRules(std::vector<std::string>& out, std::int64_t shipping, std::int64_t tax) {
    addAppliedWhen(out, "free-shipping", shipping == 0);
    addAppliedWhen(out, "tax", tax > 0);
}

std::vector<std::string> appliedAdjustments(std::int64_t tier, std::int64_t coupon,
                                      std::int64_t shipping, std::int64_t tax) {
    std::vector<std::string> out;
    addDiscountRules(out, tier, coupon);
    addChargeRules(out, shipping, tax);
    return out;
}

Quote quoteFields(const std::vector<Line>& lines, const Adjusted& adjusted,
               std::int64_t shipping, std::int64_t tax) {
    return Quote{lines, adjusted.subtotal, adjusted.tier_discount, adjusted.coupon_discount,
                 shipping, tax, adjusted.net + shipping + tax, {}};
}

Outcome quoteOutcome(const std::vector<Line>& lines, const Adjusted& adjusted,
                    std::int64_t shipping, std::int64_t tax) {
    Quote quote = quoteFields(lines, adjusted, shipping, tax);
    quote.applied =
        appliedAdjustments(adjusted.tier_discount, adjusted.coupon_discount, shipping, tax);
    return Outcome{false, QuoteError{}, quote};
}

Costs regionRates(const std::string& region) {
    if (region == "US") { return Costs{700, 500, 7500}; }
    if (region == "ASIA") { return Costs{1000, 1200, 15000}; }
    return Costs{2000, 800, 10000};
}

std::int64_t shippingFor(const Costs& costs, std::int64_t net, bool freeShipping) {
    return freeShipping || net >= costs.threshold ? 0 : costs.freight;
}

std::int64_t taxFor(std::int64_t net, std::int64_t points) {
    return (2 * net * points + 10000) / 20000;
}

Outcome settleQuote(const Priced& priced, const Adjusted& adjusted, const Normalised& request) {
    const Costs costs = regionRates(request.region);
    const std::int64_t shipping = shippingFor(costs, adjusted.net, request.coupon.free_shipping);
    const std::int64_t tax = taxFor(adjusted.net, costs.points);
    return quoteOutcome(priced.lines, adjusted, shipping, tax);
}

Outcome finishQuote(const Priced& priced, const Adjusted& adjusted, const Normalised& request) {
    return settleQuote(priced, adjusted, request);
}

Outcome completeQuote(const Merged& merged, const Normalised& normal) {
    const Priced priced = pricedLines(merged);
    const Adjusted adjusted = adjustSubtotal(priced, normal);
    return finishQuote(priced, adjusted, normal);
}

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    const Normalised normal = normaliseRequest(request);
    try {
        return completeQuote(mergedItems(validateItems(normal.items), normal), normal);
    } catch (const Rejection& rejection) {
        return Outcome{true, rejection.error, Quote{}};
    }
}
