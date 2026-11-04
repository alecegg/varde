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

bool byteIsPlain(char byte) {
    return static_cast<unsigned char>(byte) < 128;
}

bool productValid(const SaleRow& row) {
    return !row.product.empty() && std::all_of(row.product.begin(), row.product.end(), byteIsPlain);
}

bool quantityValid(const SaleRow& row) {
    return row.quantity >= 1 && row.quantity <= kMaxCount;
}

bool priceValid(const SaleRow& row) {
    return row.cents >= 0 && row.cents <= kMaxPrice;
}

bool rowUsable(const SaleRow& row) {
    return productValid(row) && quantityValid(row) && priceValid(row);
}

bool allRowsValid(const std::vector<SaleRow>& rows) {
    return std::all_of(rows.begin(), rows.end(), rowUsable);
}

Totals mergedTotals(Totals running, const SaleRow& row) {
    return Totals{running.quantity + row.quantity, running.revenue + row.cents * row.quantity};
}

void addedToTotals(TotalsMap& totals, const SaleRow& row) {
    totals[row.product] = mergedTotals(totals[row.product], row);
}

TotalsMap accumulatedRow(TotalsMap totals, const SaleRow& row) {
    return (addedToTotals(totals, row), totals);
}

TotalsMap totalsByProduct(const std::vector<SaleRow>& rows) {
    return std::accumulate(rows.begin(), rows.end(), TotalsMap{}, accumulatedRow);
}

ProductTotal recordFor(const Entry& entry) {
    return ProductTotal{entry.first, entry.second.quantity, entry.second.revenue};
}

Rows appendedRecord(Rows listed, const Entry& entry) {
    return (listed.push_back(recordFor(entry)), listed);
}

Rows recordsOf(const TotalsMap& totals) {
    return std::accumulate(totals.begin(), totals.end(), Rows{}, appendedRecord);
}

std::vector<ProductTotal> rejectedRow() {
    throw std::invalid_argument("invalid_row");
}

/** Summarize valid sales rows by product, with quantity and revenue totals in name order. */
std::vector<ProductTotal> solution(const std::vector<SaleRow>& rows) {
    return allRowsValid(rows) ? recordsOf(totalsByProduct(rows)) : rejectedRow();
}
