#include <map>
#include <stdexcept>
#include <string>
#include <vector>

struct SaleRow {
    std::string product;
    long long quantity;
    long long cents;
};

struct Totals {
    long long quantity;
    long long revenue;
};

struct ProductTotal {
    std::string product;
    long long quantity;
    long long revenue;
};

using TotalsMap = std::map<std::string, Totals>;
using Entry = TotalsMap::value_type;
using Rows = std::vector<ProductTotal>;

constexpr long long kMaxCount = 1'000'000;
constexpr long long kMaxPrice = 1'000'000'000'000;


void requireNamedProducts(const std::vector<SaleRow>& rows) {
    for (const SaleRow& row : rows) {
        bool plain = !row.product.empty();
        for (const char byte : row.product) {
            if (static_cast<unsigned char>(byte) >= 128) {
                plain = false;
            }
        }
        if (!plain) {
            throw std::invalid_argument("invalid_row");
        }
    }
}

void requireRanges(const std::vector<SaleRow>& rows) {
    for (const SaleRow& row : rows) {
        const bool counted = row.quantity >= 1 && row.quantity <= kMaxCount;
        const bool priced = row.cents >= 0 && row.cents <= kMaxPrice;
        if (!counted || !priced) {
            throw std::invalid_argument("invalid_row");
        }
    }
}

TotalsMap grouped(const std::vector<SaleRow>& rows) {
    TotalsMap totals;
    for (const SaleRow& row : rows) {
        Totals& entry = totals[row.product];
        entry.quantity += row.quantity;
        entry.revenue += row.cents * row.quantity;
    }
    return totals;
}

Rows listedRows(const TotalsMap& totals) {
    Rows listed;
    listed.reserve(totals.size());
    for (const Entry& entry : totals) {
        listed.push_back(ProductTotal{entry.first, entry.second.quantity, entry.second.revenue});
    }
    return listed;
}

/** Summarize valid sales rows by product, with quantity and revenue totals in name order. */
std::vector<ProductTotal> solution(const std::vector<SaleRow>& rows) {
    requireNamedProducts(rows);
    requireRanges(rows);
    const TotalsMap totals = grouped(rows);
    return listedRows(totals);
}
