#include <algorithm>
#include <map>
#include <numeric>
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

bool plainByte(char byte) {
    return static_cast<unsigned char>(byte) < 128;
}

bool productOk(const SaleRow& row) {
    return !row.product.empty() && std::all_of(row.product.begin(), row.product.end(), plainByte);
}

bool quantityOk(const SaleRow& row) {
    return row.quantity >= 1 && row.quantity <= kMaxCount;
}

bool priceOk(const SaleRow& row) {
    return row.cents >= 0 && row.cents <= kMaxPrice;
}

bool rowValid(const SaleRow& row) {
    return productOk(row) && quantityOk(row) && priceOk(row);
}

bool usable(const std::vector<SaleRow>& rows) {
    return std::all_of(rows.begin(), rows.end(), rowValid);
}

Totals combined(Totals total, const SaleRow& row) {
    return Totals{total.quantity + row.quantity, total.revenue + row.cents * row.quantity};
}

void recordRow(TotalsMap& totals, const SaleRow& row) {
    totals[row.product] = combined(totals[row.product], row);
}

TotalsMap grown(TotalsMap totals, const SaleRow& row) {
    return (recordRow(totals, row), totals);
}

TotalsMap totalled(const std::vector<SaleRow>& rows) {
    return std::accumulate(rows.begin(), rows.end(), TotalsMap{}, grown);
}

ProductTotal record(const Entry& entry) {
    return ProductTotal{entry.first, entry.second.quantity, entry.second.revenue};
}

Rows appended(Rows out, const Entry& entry) {
    return (out.push_back(record(entry)), out);
}

Rows recorded(const TotalsMap& totals) {
    return std::accumulate(totals.begin(), totals.end(), Rows{}, appended);
}

std::vector<ProductTotal> refused() {
    throw std::invalid_argument("invalid_row");
}

/** Summarize valid sales rows by product, with quantity and revenue totals in name order. */
std::vector<ProductTotal> solution(const std::vector<SaleRow>& rows) {
    return usable(rows) ? recorded(totalled(rows)) : refused();
}
