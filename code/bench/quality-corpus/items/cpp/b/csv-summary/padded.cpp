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

constexpr long long kMaxCount = 1'000'000;
constexpr long long kMaxPrice = 1'000'000'000'000;

bool byteIsPlain(char byte) {
    const unsigned char value = static_cast<unsigned char>(byte);
    const int limit = 128;
    const bool plain = value < static_cast<unsigned char>(limit);
    return plain;
}

bool productWithinLimits(const SaleRow& row) {
    const std::string& product = row.product;
    const bool present = !product.empty();
    const auto first = product.begin();
    const auto last = product.end();
    const bool plain = std::all_of(first, last, byteIsPlain);
    return present && plain;
}

bool countWithinLimits(const SaleRow& row) {
    const long long quantity = row.quantity;
    const bool atLeastOne = quantity >= 1;
    const bool atMostCeiling = quantity <= kMaxCount;
    return atLeastOne && atMostCeiling;
}

bool priceWithinLimits(const SaleRow& row) {
    const long long cents = row.cents;
    const bool atOrAboveZero = cents >= 0;
    const bool atOrBelowCeiling = cents <= kMaxPrice;
    return atOrAboveZero && atOrBelowCeiling;
}

bool rowWithinLimits(const SaleRow& row) {
    const bool productFine = productWithinLimits(row);
    const bool countFine = countWithinLimits(row);
    const bool priceFine = priceWithinLimits(row);
    return productFine && countFine && priceFine;
}

bool everyRowUsable(const std::vector<SaleRow>& rows) {
    const auto first = rows.begin();
    const auto last = rows.end();
    const bool usable = std::all_of(first, last, rowWithinLimits);
    return usable;
}

Totals mergedEntry(Totals running, const SaleRow& row) {
    const long long quantity = running.quantity + row.quantity;
    const long long revenue = running.revenue + row.cents * row.quantity;
    const Totals merged{quantity, revenue};
    return merged;
}

void storedRow(TotalsMap& totals, const SaleRow& row) {
    const std::string& product = row.product;
    const Totals merged = mergedEntry(totals[product], row);
    totals[product] = merged;
}

TotalsMap absorbedRow(TotalsMap totals, const SaleRow& row) {
    const bool fresh = totals.find(row.product) == totals.end();
    if (fresh) {
        const Totals none = {0, 0};
        totals[row.product] = none;
    }
    storedRow(totals, row);
    return totals;
}

TotalsMap groupedTotals(const std::vector<SaleRow>& rows) {
    const auto first = rows.begin();
    const auto last = rows.end();
    const TotalsMap totals = std::accumulate(first, last, TotalsMap{}, absorbedRow);
    return totals;
}

ProductTotal recordOfEntry(const Entry& entry) {
    const std::string& product = entry.first;
    const long long quantity = entry.second.quantity;
    const long long revenue = entry.second.revenue;
    return ProductTotal{product, quantity, revenue};
}

std::vector<ProductTotal> addedRecord(std::vector<ProductTotal> out, const Entry& entry) {
    const ProductTotal row = recordOfEntry(entry);
    out.push_back(row);
    return out;
}

std::vector<ProductTotal> listedRecords(const TotalsMap& totals) {
    const auto first = totals.begin();
    const auto last = totals.end();
    const std::vector<ProductTotal> listed =
        std::accumulate(first, last, std::vector<ProductTotal>{}, addedRecord);
    return listed;
}

std::vector<ProductTotal> raiseInvalidRow() {
    const std::string reason = "invalid_row";
    const std::invalid_argument failure(reason);
    throw failure;
}

/** Summarize valid sales rows by product, with quantity and revenue totals in name order. */
std::vector<ProductTotal> solution(const std::vector<SaleRow>& rows) {
    return everyRowUsable(rows) ? listedRecords(groupedTotals(rows)) : raiseInvalidRow();
}
