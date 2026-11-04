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

struct CheckedItem {
    std::string sku;
    std::int64_t qty;
    std::int64_t cents;
};

struct Amount {
    std::int64_t qty;
    std::int64_t cents;
};

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    std::size_t tier_first = 0;
    while (tier_first < request.tier.size() &&
           std::isspace(static_cast<unsigned char>(request.tier[tier_first])) != 0) {
        tier_first += 1;
    }
    std::size_t tier_last = request.tier.size();
    while (tier_last > tier_first &&
           std::isspace(static_cast<unsigned char>(request.tier[tier_last - 1])) != 0) {
        tier_last -= 1;
    }
    std::string tier_text = request.tier.substr(tier_first, tier_last - tier_first);
    for (char& letter : tier_text) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    std::size_t coupon_first = 0;
    while (coupon_first < request.coupon.size() &&
           std::isspace(static_cast<unsigned char>(request.coupon[coupon_first])) != 0) {
        coupon_first += 1;
    }
    std::size_t coupon_last = request.coupon.size();
    while (coupon_last > coupon_first &&
           std::isspace(static_cast<unsigned char>(request.coupon[coupon_last - 1])) != 0) {
        coupon_last -= 1;
    }
    std::string coupon_text =
        request.coupon.substr(coupon_first, coupon_last - coupon_first);
    for (char& letter : coupon_text) {
        if (letter >= 'a' && letter <= 'z') {
            letter = static_cast<char>(letter - 'a' + 'A');
        }
    }
    bool coupon_valid = true;
    bool coupon_percent = false;
    bool coupon_free_shipping = false;
    std::int64_t coupon_amount = 0;
    if (coupon_text == "FREESHIP") {
        coupon_free_shipping = true;
    } else if (!coupon_text.empty()) {
        if (coupon_text.compare(0, 3, "PCT") == 0) {
            const std::string digits = coupon_text.substr(3);
            std::int64_t amount = 0;
            bool readable = !digits.empty() && digits[0] != '0';
            for (const char letter : digits) {
                if (letter < '0' || letter > '9') {
                    readable = false;
                } else if (readable) {
                    amount = amount * 10 + (letter - '0');
                    if (amount > 50) {
                        readable = false;
                    }
                }
            }
            if (readable) {
                coupon_percent = true;
                coupon_amount = amount;
            } else {
                coupon_valid = false;
            }
        } else if (coupon_text.compare(0, 5, "FIXED") == 0) {
            const std::string digits = coupon_text.substr(5);
            std::int64_t amount = 0;
            bool readable = !digits.empty() && digits[0] != '0';
            for (const char letter : digits) {
                if (letter < '0' || letter > '9') {
                    readable = false;
                } else if (readable) {
                    amount = amount * 10 + (letter - '0');
                    if (amount > 500) {
                        readable = false;
                    }
                }
            }
            if (readable) {
                coupon_amount = amount;
            } else {
                coupon_valid = false;
            }
        } else {
            coupon_valid = false;
        }
    }

    std::size_t region_first = 0;
    while (region_first < request.region.size() &&
           std::isspace(static_cast<unsigned char>(request.region[region_first])) != 0) {
        region_first += 1;
    }
    std::size_t region_last = request.region.size();
    while (region_last > region_first &&
           std::isspace(static_cast<unsigned char>(request.region[region_last - 1])) != 0) {
        region_last -= 1;
    }
    std::string region_text = request.region.substr(region_first, region_last - region_first);
    for (char& letter : region_text) {
        if (letter >= 'a' && letter <= 'z') {
            letter = static_cast<char>(letter - 'a' + 'A');
        }
    }

    if (request.items.empty()) {
        return Outcome{true, QuoteError{"EMPTY_ORDER", false, 0}, Quote{}};
    }
    if (request.items.size() > 50) {
        return Outcome{true, QuoteError{"TOO_MANY_ITEMS", false, 0}, Quote{}};
    }

    std::vector<CheckedItem> checked;
    checked.reserve(request.items.size());
    for (std::size_t position = 0; position < request.items.size(); position += 1) {
        const RawItem& raw = request.items[position];
        const std::int64_t index = static_cast<std::int64_t>(position);

        std::size_t sku_first = 0;
        while (sku_first < raw.sku.size() &&
               std::isspace(static_cast<unsigned char>(raw.sku[sku_first])) != 0) {
            sku_first += 1;
        }
        std::size_t sku_last = raw.sku.size();
        while (sku_last > sku_first &&
               std::isspace(static_cast<unsigned char>(raw.sku[sku_last - 1])) != 0) {
            sku_last -= 1;
        }
        std::string sku_text = raw.sku.substr(sku_first, sku_last - sku_first);
        for (char& letter : sku_text) {
            if (letter >= 'a' && letter <= 'z') {
                letter = static_cast<char>(letter - 'a' + 'A');
            }
        }
        bool sku_ok = sku_text.size() >= 3 && sku_text.size() <= 12;
        if (sku_ok) {
            for (const char letter : sku_text) {
                const bool capital = letter >= 'A' && letter <= 'Z';
                const bool digit = letter >= '0' && letter <= '9';
                if (!capital && !digit && letter != '-') {
                    sku_ok = false;
                }
            }
        }
        if (!sku_ok) {
            return Outcome{true, QuoteError{"BAD_SKU", true, index}, Quote{}};
        }
        if (raw.qty < 1 || raw.qty > 1000) {
            return Outcome{true, QuoteError{"BAD_QTY", true, index}, Quote{}};
        }

        bool price_ok = true;
        bool point_seen = false;
        std::size_t whole_digits = 0;
        std::size_t fraction_digits = 0;
        for (const char letter : raw.price) {
            if (letter == '.') {
                if (point_seen) {
                    price_ok = false;
                }
                point_seen = true;
            } else if (letter >= '0' && letter <= '9') {
                if (point_seen) {
                    fraction_digits += 1;
                } else {
                    whole_digits += 1;
                }
            } else {
                price_ok = false;
            }
        }
        if (whole_digits < 1 || whole_digits > 6 || fraction_digits > 2 ||
            (point_seen && fraction_digits == 0)) {
            price_ok = false;
        }
        std::int64_t cents = 0;
        if (price_ok) {
            const std::size_t point = raw.price.find('.');
            const std::string whole =
                point == std::string::npos ? raw.price : raw.price.substr(0, point);
            const std::string fraction =
                point == std::string::npos ? "" : raw.price.substr(point + 1);
            std::int64_t units = 0;
            for (const char letter : whole) {
                units = units * 10 + (letter - '0');
            }
            std::int64_t tail = 0;
            for (const char letter : fraction) {
                tail = tail * 10 + (letter - '0');
            }
            cents = units * 100;
            if (fraction.size() == 1) {
                cents += tail * 10;
            } else if (fraction.size() == 2) {
                cents += tail;
            }
        }
        if (!price_ok || cents <= 0) {
            return Outcome{true, QuoteError{"BAD_PRICE", true, index}, Quote{}};
        }
        checked.push_back(CheckedItem{sku_text, raw.qty, cents});
    }

    std::map<std::string, Amount> merged;
    for (std::size_t position = 0; position < checked.size(); position += 1) {
        const CheckedItem& current = checked[position];
        const std::int64_t index = static_cast<std::int64_t>(position);
        const auto found = merged.find(current.sku);
        if (found == merged.end()) {
            merged[current.sku] = Amount{current.qty, current.cents};
        } else if (found->second.cents != current.cents) {
            return Outcome{true, QuoteError{"PRICE_CONFLICT", true, index}, Quote{}};
        } else {
            found->second.qty += current.qty;
            if (found->second.qty > 1000) {
                return Outcome{true, QuoteError{"BAD_QTY", true, index}, Quote{}};
            }
        }
    }

    const bool tier_known =
        tier_text == "basic" || tier_text == "silver" || tier_text == "gold";
    if (!tier_known) {
        return Outcome{true, QuoteError{"BAD_TIER", false, 0}, Quote{}};
    }
    if (!coupon_valid) {
        return Outcome{true, QuoteError{"BAD_COUPON", false, 0}, Quote{}};
    }
    const bool region_known =
        region_text == "EU" || region_text == "US" || region_text == "ASIA";
    if (!region_known) {
        return Outcome{true, QuoteError{"BAD_REGION", false, 0}, Quote{}};
    }

    Quote quote;
    std::int64_t subtotal = 0;
    for (const auto& entry : merged) {
        const std::int64_t line_cents = entry.second.qty * entry.second.cents;
        quote.lines.push_back(
            Line{entry.first, entry.second.qty, entry.second.cents, line_cents});
        subtotal += line_cents;
    }
    quote.subtotal = subtotal;

    std::int64_t tier_points = 0;
    if (tier_text == "silver") {
        tier_points = 500;
    } else if (tier_text == "gold") {
        tier_points = 1000;
    }
    const std::int64_t tier_scaled = 2 * subtotal * tier_points;
    quote.tier_discount = (tier_scaled + 10000) / 20000;
    const std::int64_t after_tier = subtotal - quote.tier_discount;
    if (coupon_amount == 0) {
        quote.coupon_discount = 0;
    } else if (coupon_percent) {
        const std::int64_t coupon_scaled = 2 * after_tier * coupon_amount;
        quote.coupon_discount = (coupon_scaled + 100) / 200;
    } else {
        const std::int64_t requested = coupon_amount * 100;
        quote.coupon_discount = requested < after_tier ? requested : after_tier;
    }
    const std::int64_t net = after_tier - quote.coupon_discount;

    std::int64_t freight = 800;
    std::int64_t threshold = 10000;
    std::int64_t tax_points = 2000;
    if (region_text == "US") {
        freight = 500;
        threshold = 7500;
        tax_points = 700;
    } else if (region_text == "ASIA") {
        freight = 1200;
        threshold = 15000;
        tax_points = 1000;
    }
    if (coupon_free_shipping || net >= threshold) {
        quote.shipping = 0;
    } else {
        quote.shipping = freight;
    }
    const std::int64_t tax_scaled = 2 * net * tax_points;
    quote.tax = (tax_scaled + 10000) / 20000;
    quote.total = net + quote.shipping + quote.tax;

    const bool tier_applied = quote.tier_discount > 0;
    const bool coupon_applied = quote.coupon_discount > 0;
    const bool shipping_applied = quote.shipping == 0;
    const bool tax_applied = quote.tax > 0;
    if (tier_applied) {
        quote.applied.push_back("tier");
    }
    if (coupon_applied) {
        quote.applied.push_back("coupon");
    }
    if (shipping_applied) {
        quote.applied.push_back("free-shipping");
    }
    if (tax_applied) {
        quote.applied.push_back("tax");
    }
    return Outcome{false, QuoteError{}, quote};
}
