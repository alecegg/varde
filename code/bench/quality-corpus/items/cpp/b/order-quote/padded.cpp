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

struct NumberReading {
    bool accepted;
    std::int64_t value;
};

struct NormalisedOrder {
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

using MergedOrder = std::map<std::string, Amount>;

struct Priced {
    std::vector<Line> lines;
    std::int64_t subtotal;
};

struct Discount {
    std::int64_t amount;
};

struct Shipping {
    std::int64_t freight;
    bool waived;
};

struct Tax {
    std::int64_t amount;
};

struct Adjustment {
    std::int64_t tier_discount;
    std::int64_t coupon_discount;
    std::int64_t net;
    std::int64_t shipping;
    std::int64_t tax;
};

struct AppliedRules {
    std::vector<std::string> names;
};

const Coupon kPlainCoupon{true, false, false, 0};
const Coupon kFreeCoupon{true, false, true, 0};
const Coupon kNoCoupon{false, false, false, 0};
const QuoteError kAccepted{};
const NumberReading kNoReading{false, 0};

std::string trimText(const std::string& text) {
    const std::string blanks = " \t\n\r\v\f";
    const std::size_t first = text.find_first_not_of(blanks);
    if (first == std::string::npos) {
        return "";
    }
    const std::size_t last = text.find_last_not_of(blanks);
    return text.substr(first, last - first + 1);
}

std::string raiseText(const std::string& text) {
    std::string raised;
    raised.reserve(text.size());
    for (const char letter : text) {
        const bool lowered = letter >= 'a' && letter <= 'z';
        raised.push_back(lowered ? static_cast<char>(letter - 'a' + 'A') : letter);
    }
    return raised;
}

NumberReading couponDigits(const std::string& digits, std::int64_t limit) {
    std::int64_t total = 0;
    for (const char letter : digits) {
        if (letter < '0' || letter > '9') {
            return kNoReading;
        }
        total = total * 10 + (letter - '0');
        if (total > limit) {
            return kNoReading;
        }
    }
    const bool accepted = !digits.empty() && digits[0] != '0';
    return NumberReading{accepted, accepted ? total : 0};
}

Coupon parseCoupon(const std::string& text) {
    if (text.empty()) {
        return kPlainCoupon;
    }
    if (text == "FREESHIP") {
        return kFreeCoupon;
    }
    const bool percent = text.rfind("PCT", 0) == 0;
    if (!percent && text.rfind("FIXED", 0) != 0) {
        return kNoCoupon;
    }
    const NumberReading reading = couponDigits(text.substr(percent ? 3 : 5), percent ? 50 : 500);
    return Coupon{reading.accepted, percent, false, reading.value};
}

std::vector<RawItem> normaliseItems(const std::vector<RawItem>& items) {
    std::vector<RawItem> normalised;
    normalised.reserve(items.size());
    for (const RawItem& item : items) {
        normalised.push_back(RawItem{raiseText(trimText(item.sku)), item.qty, item.price});
    }
    return normalised;
}

NormalisedOrder normaliseRequest(const Request& request) {
    NormalisedOrder order;
    order.items = normaliseItems(request.items);
    order.tier = trimText(request.tier);
    for (char& letter : order.tier) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    order.coupon = parseCoupon(raiseText(trimText(request.coupon)));
    order.region = raiseText(trimText(request.region));
    return order;
}

std::int64_t priceCents(const std::string& text) {
    const std::size_t point = text.find('.');
    if (point == std::string::npos) {
        return std::stoll(text) * 100;
    }
    const std::string fraction = text.substr(point + 1);
    const std::int64_t tail = std::stoll(fraction);
    return std::stoll(text.substr(0, point)) * 100 + tail * (fraction.size() == 1 ? 10 : 1);
}

bool skuAcceptable(const std::string& sku) {
    const bool length_ok = sku.size() >= 3 && sku.size() <= 12;
    const bool letters_ok = sku.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-") ==
                            std::string::npos;
    return length_ok && letters_ok;
}

bool priceDigits(const std::string& text, std::size_t& whole, std::size_t& fraction) {
    std::size_t points = 0;
    for (const char letter : text) {
        if (letter == '.') {
            points += 1;
            if (points > 1) {
                return false;
            }
        } else if (letter < '0' || letter > '9') {
            return false;
        } else if (points > 0) {
            fraction += 1;
        } else {
            whole += 1;
        }
    }
    return true;
}

NumberReading readPrice(const std::string& text) {
    std::size_t whole = 0;
    std::size_t fraction = 0;
    if (!priceDigits(text, whole, fraction)) {
        return kNoReading;
    }
    const bool has_point = text.find('.') != std::string::npos;
    if (whole < 1 || whole > 6 || fraction > 2 || (has_point && fraction == 0)) {
        return kNoReading;
    }
    const std::int64_t cents = priceCents(text);
    return NumberReading{cents > 0, cents};
}

QuoteError checkItem(const RawItem& item, std::int64_t index, CheckedItem& checked) {
    if (!skuAcceptable(item.sku)) {
        return QuoteError{"BAD_SKU", true, index};
    }
    if (item.qty < 1 || item.qty > 1000) {
        return QuoteError{"BAD_QTY", true, index};
    }
    const NumberReading price{readPrice(item.price)};
    if (!price.accepted) {
        return QuoteError{"BAD_PRICE", true, index};
    }
    checked = {item.sku, item.qty, price.value};
    return kAccepted;
}

QuoteError mergeOne(MergedOrder& merged, const CheckedItem& item, std::int64_t index) {
    Amount& slot = merged[item.sku];
    if (slot.qty != 0 && slot.cents != item.cents) {
        return QuoteError{"PRICE_CONFLICT", true, index};
    }
    slot.qty += item.qty;
    if (slot.qty > 1000) {
        return QuoteError{"BAD_QTY", true, index};
    }
    slot.cents = item.cents;
    return kAccepted;
}

QuoteError checkRequestOptions(const NormalisedOrder& order) {
    if (order.tier != "basic" && order.tier != "silver" && order.tier != "gold") {
        return QuoteError{"BAD_TIER", false, 0};
    }
    if (!order.coupon.valid) {
        return QuoteError{"BAD_COUPON", false, 0};
    }
    if (order.region != "EU" && order.region != "US" && order.region != "ASIA") {
        return QuoteError{"BAD_REGION", false, 0};
    }
    return kAccepted;
}

Priced priceOrder(const MergedOrder& merged) {
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

Discount tierDiscount(std::int64_t subtotal, const std::string& tier) {
    std::int64_t basis_points = 0;
    if (tier == "silver") {
        basis_points = 500;
    } else if (tier == "gold") {
        basis_points = 1000;
    }
    return Discount{(2 * subtotal * basis_points + 10000) / 20000};
}

Discount couponDiscount(std::int64_t net, const Coupon& coupon) {
    if (coupon.amount == 0) {
        return Discount{0};
    }
    if (coupon.percent) {
        return Discount{(2 * net * coupon.amount + 100) / 200};
    }
    const std::int64_t requested = coupon.amount * 100;
    return Discount{requested < net ? requested : net};
}

Shipping shippingFor(const std::string& region, std::int64_t net, const Coupon& coupon) {
    std::int64_t freight = 800;
    std::int64_t threshold = 10000;
    if (region == "US") {
        freight = 500;
        threshold = 7500;
    } else if (region == "ASIA") {
        freight = 1200;
        threshold = 15000;
    }
    const bool waived = coupon.free_shipping || net >= threshold;
    return Shipping{freight, waived};
}

Tax taxFor(const std::string& region, std::int64_t net) {
    std::int64_t basis_points = 2000;
    if (region == "US") {
        basis_points = 700;
    } else if (region == "ASIA") {
        basis_points = 1000;
    }
    return Tax{(2 * net * basis_points + 10000) / 20000};
}

Adjustment adjustOrder(const NormalisedOrder& order, const Priced& priced) {
    const Discount tier_cut = tierDiscount(priced.subtotal, order.tier);
    const Discount coupon_cut = couponDiscount(priced.subtotal - tier_cut.amount, order.coupon);
    const std::int64_t net = priced.subtotal - tier_cut.amount - coupon_cut.amount;
    const Shipping freight = shippingFor(order.region, net, order.coupon);
    const Tax tax = taxFor(order.region, net);
    return Adjustment{tier_cut.amount, coupon_cut.amount, net,
                      freight.waived ? 0 : freight.freight, tax.amount};
}

AppliedRules appliedRules(const Adjustment& adjustment) {
    AppliedRules applied;
    if (adjustment.tier_discount > 0) {
        applied.names.push_back("tier");
    }
    if (adjustment.coupon_discount > 0) {
        applied.names.push_back("coupon");
    }
    if (adjustment.shipping == 0) {
        applied.names.push_back("free-shipping");
    }
    if (adjustment.tax > 0) {
        applied.names.push_back("tax");
    }
    return applied;
}

Outcome assembleOutcome(const Priced& priced, const Adjustment& adjustment) {
    const AppliedRules applied = appliedRules(adjustment);
    Quote quote;
    quote.lines = priced.lines;
    quote.subtotal = priced.subtotal;
    quote.tier_discount = adjustment.tier_discount;
    quote.coupon_discount = adjustment.coupon_discount;
    quote.shipping = adjustment.shipping;
    quote.tax = adjustment.tax;
    quote.total = adjustment.net + adjustment.shipping + adjustment.tax;
    quote.applied = applied.names;
    return Outcome{false, QuoteError{}, quote};
}

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    const NormalisedOrder order = normaliseRequest(request);
    if (order.items.empty()) {
        return Outcome{true, QuoteError{"EMPTY_ORDER", false, 0}, Quote{}};
    }
    if (order.items.size() > 50) {
        return Outcome{true, QuoteError{"TOO_MANY_ITEMS", false, 0}, Quote{}};
    }
    std::vector<CheckedItem> checked;
    for (std::size_t position = 0; position < order.items.size(); position += 1) {
        CheckedItem item;
        const QuoteError error =
            checkItem(order.items[position], static_cast<std::int64_t>(position), item);
        if (!error.code.empty()) {
            return Outcome{true, error, Quote{}};
        }
        checked.push_back(item);
    }
    MergedOrder merged;
    for (std::size_t position = 0; position < checked.size(); position += 1) {
        const QuoteError error =
            mergeOne(merged, checked[position], static_cast<std::int64_t>(position));
        if (!error.code.empty()) {
            return Outcome{true, error, Quote{}};
        }
    }
    const QuoteError option_error = checkRequestOptions(order);
    if (!option_error.code.empty()) {
        return Outcome{true, option_error, Quote{}};
    }
    const Priced priced = priceOrder(merged);
    const Adjustment adjustment = adjustOrder(order, priced);
    return assembleOutcome(priced, adjustment);
}
