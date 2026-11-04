#include <algorithm>
#include <cstddef>
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
    for (std::size_t index = 0; index < rows.size(); index += 1) {
        const SaleRow& row = rows[index];
        const bool missingProduct = row.product.empty();
        if (missingProduct) {
            throw std::invalid_argument("invalid_row");
        }
        for (std::size_t position = 0; position < row.product.size(); position += 1) {
            const unsigned char byte = static_cast<unsigned char>(row.product[position]);
            if (byte >= 128) {
                throw std::invalid_argument("invalid_row");
            }
        }
        if (row.quantity < 1) {
            throw std::invalid_argument("invalid_row");
        }
        if (row.quantity > kMaxCount) {
            throw std::invalid_argument("invalid_row");
        }
        if (row.cents < 0) {
            throw std::invalid_argument("invalid_row");
        }
        if (row.cents > kMaxPrice) {
            throw std::invalid_argument("invalid_row");
        }
    }
    TotalsMap totals;
    for (std::size_t index = 0; index < rows.size(); index += 1) {
        const SaleRow& row = rows[index];
        const std::string& product = row.product;
        if (totals.find(product) == totals.end()) {
            Totals fresh;
            fresh.quantity = 0;
            fresh.revenue = 0;
            totals[product] = fresh;
        }
        const long long units = row.quantity;
        const long long line = row.cents * units;
        Totals& entry = totals[product];
        const long long quantitySoFar = entry.quantity;
        const long long revenueSoFar = entry.revenue;
        entry.quantity = quantitySoFar + units;
        entry.revenue = revenueSoFar + line;
    }
    std::vector<ProductTotal> listed;
    listed.reserve(totals.size());
    for (std::size_t index = 0; index < totals.size(); index += 1) {
        const auto position = std::next(totals.begin(), static_cast<long>(index));
        const Entry& entry = *position;
        const Totals& counted = entry.second;
        ProductTotal record;
        record.product = entry.first;
        record.quantity = counted.quantity;
        record.revenue = counted.revenue;
        listed.push_back(record);
    }
    return listed;
}
