#include <algorithm>
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

constexpr long long kMaxCount = 1'000'000;
constexpr long long kMaxPrice = 1'000'000'000'000;

/** Summarize valid sales rows by product, with quantity and revenue totals in name order. */
std::vector<ProductTotal> solution(const std::vector<SaleRow>& rows) {
    for (const SaleRow& row : rows) {
        const bool plain = std::all_of(row.product.begin(), row.product.end(), [](char byte) {
            return static_cast<unsigned char>(byte) < 128;
        });
        const bool named = !row.product.empty() && plain;
        if (!named) {
            throw std::invalid_argument("invalid_row");
        }
        const bool counted = row.quantity >= 1 && row.quantity <= kMaxCount;
        const bool priced = row.cents >= 0 && row.cents <= kMaxPrice;
        if (!counted) {
            throw std::invalid_argument("invalid_row");
        }
        if (!priced) {
            throw std::invalid_argument("invalid_row");
        }
    }
    TotalsMap totals;
    for (const SaleRow& row : rows) {
        const std::string& product = row.product;
        const long long units = row.quantity;
        Totals& entry = totals[product];
        const long long line = row.cents * units;
        const long long revenue = entry.revenue + line;
        entry.quantity += units;
        entry.revenue = revenue;
    }
    std::vector<ProductTotal> listed;
    listed.reserve(totals.size());
    for (const Entry& entry : totals) {
        const std::string& product = entry.first;
        const long long quantity = entry.second.quantity;
        const long long revenue = entry.second.revenue;
        listed.push_back(ProductTotal{product, quantity, revenue});
    }
    return listed;
}
