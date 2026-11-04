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

struct Entry {
    std::string sku;
    std::int64_t qty;
    std::int64_t cents;
};

/** Quote normalized order lines with discounts, shipping, tax, and applied adjustments. */
Outcome solution(const Request& request) {
    const std::string blanks = " \t\n\r\v\f";

    const std::size_t tier_first = request.tier.find_first_not_of(blanks);
    const bool has_tier = tier_first != std::string::npos;
    const std::size_t tier_last =
        has_tier ? request.tier.find_last_not_of(blanks) + 1 : std::string::npos;
    std::string tier = has_tier ? request.tier.substr(tier_first, tier_last - tier_first) : "";
    for (char& letter : tier) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    const std::size_t coupon_first = request.coupon.find_first_not_of(blanks);
    const bool has_coupon_text = coupon_first != std::string::npos;
    const std::size_t coupon_last = has_coupon_text
                                        ? request.coupon.find_last_not_of(blanks) + 1
                                        : std::string::npos;
    std::string coupon_text = has_coupon_text
                                  ? request.coupon.substr(coupon_first, coupon_last - coupon_first)
                                  : "";
    for (char& letter : coupon_text) {
        if (letter >= 'a' && letter <= 'z') {
            letter = static_cast<char>(letter - 'a' + 'A');
        }
    }

    const std::size_t region_first = request.region.find_first_not_of(blanks);
    const bool has_region = region_first != std::string::npos;
    const std::size_t region_last =
        has_region ? request.region.find_last_not_of(blanks) + 1 : std::string::npos;
    std::string region =
        has_region ? request.region.substr(region_first, region_last - region_first) : "";
    for (char& letter : region) {
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

    std::vector<RawItem> normal;
    normal.reserve(request.items.size());
    for (const RawItem& raw : request.items) {
        const std::size_t sku_first = raw.sku.find_first_not_of(blanks);
        const bool has_sku = sku_first != std::string::npos;
        const std::size_t sku_last =
            has_sku ? raw.sku.find_last_not_of(blanks) + 1 : std::string::npos;
        std::string sku = has_sku ? raw.sku.substr(sku_first, sku_last - sku_first) : "";
        for (char& letter : sku) {
            if (letter >= 'a' && letter <= 'z') {
                letter = static_cast<char>(letter - 'a' + 'A');
            }
        }
        normal.push_back(RawItem{sku, raw.qty, raw.price});
    }

    std::vector<Entry> checked;
    for (std::size_t position = 0; position < normal.size(); position += 1) {
        const RawItem& item = normal[position];
        const std::int64_t index = static_cast<std::int64_t>(position);

        const bool sku_length_ok = item.sku.size() >= 3 && item.sku.size() <= 12;
        bool sku_characters_ok = true;
        for (const char letter : item.sku) {
            const bool capital = letter >= 'A' && letter <= 'Z';
            const bool digit = letter >= '0' && letter <= '9';
            if (!capital && !digit && letter != '-') {
                sku_characters_ok = false;
            }
        }
        if (!sku_length_ok || !sku_characters_ok) {
            return Outcome{true, QuoteError{"BAD_SKU", true, index}, Quote{}};
        }
        if (item.qty < 1 || item.qty > 1000) {
            return Outcome{true, QuoteError{"BAD_QTY", true, index}, Quote{}};
        }

        bool shape_ok = true;
        bool has_point = false;
        std::size_t whole_digits = 0;
        std::size_t fraction_digits = 0;
        for (const char letter : item.price) {
            if (letter == '.') {
                if (has_point) {
                    shape_ok = false;
                }
                has_point = true;
            } else if (letter >= '0' && letter <= '9') {
                if (has_point) {
                    fraction_digits += 1;
                } else {
                    whole_digits += 1;
                }
            } else {
                shape_ok = false;
            }
        }
        const bool whole_ok = whole_digits >= 1 && whole_digits <= 6;
        const bool fraction_ok = fraction_digits <= 2 && (!has_point || fraction_digits > 0);
        if (!shape_ok || !whole_ok || !fraction_ok) {
            return Outcome{true, QuoteError{"BAD_PRICE", true, index}, Quote{}};
        }

        const std::size_t point = item.price.find('.');
        const bool has_fraction = point != std::string::npos;
        const std::string whole = has_fraction ? item.price.substr(0, point) : item.price;
        const std::string fraction = has_fraction ? item.price.substr(point + 1) : "";
        const std::int64_t units = std::stoll(whole);
        const std::int64_t tail = fraction.empty() ? 0 : std::stoll(fraction);
        const std::int64_t scale = fraction.size() == 1 ? 10 : 1;
        const std::int64_t cents = units * 100 + tail * scale;
        if (cents <= 0) {
            return Outcome{true, QuoteError{"BAD_PRICE", true, index}, Quote{}};
        }
        checked.push_back(Entry{item.sku, item.qty, cents});
    }

    std::map<std::string, Entry> merged;
    for (std::size_t position = 0; position < checked.size(); position += 1) {
        const Entry& item = checked[position];
        const std::int64_t index = static_cast<std::int64_t>(position);
        const auto found = merged.find(item.sku);
        if (found == merged.end()) {
            merged[item.sku] = item;
            continue;
        }
        const bool price_matches = found->second.cents == item.cents;
        if (!price_matches) {
            return Outcome{true, QuoteError{"PRICE_CONFLICT", true, index}, Quote{}};
        }
        found->second.qty += item.qty;
        if (found->second.qty > 1000) {
            return Outcome{true, QuoteError{"BAD_QTY", true, index}, Quote{}};
        }
    }

    const bool tier_known = tier == "basic" || tier == "silver" || tier == "gold";
    if (!tier_known) {
        return Outcome{true, QuoteError{"BAD_TIER", false, 0}, Quote{}};
    }
    bool coupon_free_shipping = false;
    bool coupon_percent = false;
    std::int64_t coupon_amount = 0;
    if (!coupon_text.empty()) {
        const bool percent = coupon_text.compare(0, 3, "PCT") == 0;
        const bool fixed = coupon_text.compare(0, 5, "FIXED") == 0;
        const bool free_shipping = coupon_text == "FREESHIP";
        const std::size_t start = percent ? 3 : 5;
        const std::int64_t limit = percent ? 50 : 500;
        const std::string digits = coupon_text.substr(start);
        bool readable = (percent || fixed) && !digits.empty() && digits[0] != '0';
        for (const char letter : digits) {
            const bool is_digit = letter >= '0' && letter <= '9';
            if (!is_digit) {
                readable = false;
            } else if (readable) {
                coupon_amount = coupon_amount * 10 + (letter - '0');
                if (coupon_amount > limit) {
                    readable = false;
                }
            }
        }
        const bool coupon_known = free_shipping || readable;
        if (!coupon_known) {
            return Outcome{true, QuoteError{"BAD_COUPON", false, 0}, Quote{}};
        }
        coupon_free_shipping = free_shipping;
        coupon_percent = percent && !free_shipping;
        if (free_shipping) {
            coupon_amount = 0;
        }
    }
    if (region != "EU" && region != "US" && region != "ASIA") {
        return Outcome{true, QuoteError{"BAD_REGION", false, 0}, Quote{}};
    }

    Quote quote;
    std::int64_t subtotal = 0;
    for (const auto& entry : merged) {
        const std::int64_t qty = entry.second.qty;
        const std::int64_t cents = entry.second.cents;
        const std::int64_t line_cents = qty * cents;
        quote.lines.push_back(Line{entry.first, qty, cents, line_cents});
        subtotal += line_cents;
    }
    quote.subtotal = subtotal;

    std::int64_t tier_points = 0;
    if (tier == "silver") {
        tier_points = 500;
    } else if (tier == "gold") {
        tier_points = 1000;
    }
    const std::int64_t tier_scaled = 2 * subtotal * tier_points;
    const std::int64_t tier_discount = (tier_scaled + 10000) / 20000;
    const std::int64_t after_tier = subtotal - tier_discount;

    std::int64_t coupon_discount = 0;
    if (coupon_percent) {
        const std::int64_t coupon_scaled = 2 * after_tier * coupon_amount;
        coupon_discount = (coupon_scaled + 100) / 200;
    } else if (coupon_amount > 0) {
        const std::int64_t requested = coupon_amount * 100;
        coupon_discount = requested < after_tier ? requested : after_tier;
    }
    const std::int64_t net = after_tier - coupon_discount;

    std::int64_t freight = 800;
    std::int64_t threshold = 10000;
    std::int64_t tax_points = 2000;
    if (region == "US") {
        freight = 500;
        threshold = 7500;
        tax_points = 700;
    } else if (region == "ASIA") {
        freight = 1200;
        threshold = 15000;
        tax_points = 1000;
    }
    const bool over_threshold = net >= threshold;
    const std::int64_t shipping = coupon_free_shipping || over_threshold ? 0 : freight;
    const std::int64_t tax_scaled = 2 * net * tax_points;
    const std::int64_t tax = (tax_scaled + 10000) / 20000;
    const std::int64_t total = net + shipping + tax;

    quote.tier_discount = tier_discount;
    quote.coupon_discount = coupon_discount;
    quote.shipping = shipping;
    quote.tax = tax;
    quote.total = total;
    const bool tier_applied = tier_discount > 0;
    const bool coupon_applied = coupon_discount > 0;
    const bool shipping_applied = shipping == 0;
    const bool tax_applied = tax > 0;
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
