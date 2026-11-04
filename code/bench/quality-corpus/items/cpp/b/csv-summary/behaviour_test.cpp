#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "solution.cpp"

struct Seen {
    std::string product;
    long long quantity;
    long long revenue;
};

std::vector<Seen> referenceOf(const std::vector<SaleRow>& rows) {
    std::vector<SaleRow> ordered = rows;
    std::sort(ordered.begin(), ordered.end(),
              [](const SaleRow& left, const SaleRow& right) { return left.product < right.product; });
    std::vector<Seen> found;
    std::size_t start = 0;
    while (start < ordered.size()) {
        std::size_t end = start;
        __int128 revenue = 0;
        long long quantity = 0;
        while (end < ordered.size() && ordered[end].product == ordered[start].product) {
            revenue += static_cast<__int128>(ordered[end].cents) * ordered[end].quantity;
            quantity += ordered[end].quantity;
            end += 1;
        }
        found.push_back(Seen{ordered[start].product, quantity, static_cast<long long>(revenue)});
        start = end;
    }
    return found;
}

void check(const std::vector<ProductTotal>& got, const std::vector<Seen>& want, const char* label) {
    bool same = got.size() == want.size();
    for (std::size_t index = 0; same && index < got.size(); index += 1) {
        same = got[index].product == want[index].product &&
               got[index].quantity == want[index].quantity &&
               got[index].revenue == want[index].revenue;
    }
    if (same) {
        return;
    }
    std::cerr << label << ": expected " << want.size() << " records but got " << got.size() << '\n';
    for (const ProductTotal& record : got) {
        std::cerr << "  got " << record.product << ' ' << record.quantity << ' ' << record.revenue
                  << '\n';
    }
    std::exit(1);
}

void checkRows(const std::vector<SaleRow>& rows, const char* label) {
    check(solution(rows), referenceOf(rows), label);
}

void checkRejected(const std::vector<SaleRow>& rows, const char* label) {
    try {
        const std::vector<ProductTotal> got = solution(rows);
        std::cerr << label << ": expected a rejection but got " << got.size() << " records\n";
        std::exit(1);
    } catch (const std::invalid_argument& error) {
        if (std::string(error.what()) != "invalid_row") {
            std::cerr << label << ": wrong message " << error.what() << '\n';
            std::exit(1);
        }
    }
}

std::vector<SaleRow> warehouse(unsigned long long seed) {
    std::vector<SaleRow> rows;
    rows.reserve(3000);
    unsigned long long state = seed;
    const auto next = [&state]() {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return state >> 33;
    };
    for (int index = 0; index < 3000; index += 1) {
        const std::string name = "P" + std::to_string(next() % 60);
        const long long quantity = 1 + static_cast<long long>(next() % 90);
        const long long cents = static_cast<long long>(next() % 120000);
        rows.push_back(SaleRow{name, quantity, cents});
    }
    return rows;
}

int main() {
    const std::vector<std::vector<SaleRow>> cases = {
        {{"Tea", 2, 300}},
        {},
        {{"Pen", 3, 120}, {"Book", 1, 800}},
        {{"Tea", 1, 200}, {"Tea", 4, 250}},
        {{"A", 1, 0}},
        {{"z", 2, 111}, {"a", 2, 111}},
        {{"Mug", 2, 450}, {"Mug", 1, 450}, {"Bag", 1, 700}},
        {{"x", 10, 5}},
        {{"same", 1, 100}, {"Same", 1, 200}},
        {{"K", 7, 235}},
    };
    const std::vector<std::vector<Seen>> expected = {
        {{"Tea", 2, 600}},
        {},
        {{"Book", 1, 800}, {"Pen", 3, 360}},
        {{"Tea", 5, 1200}},
        {{"A", 1, 0}},
        {{"a", 2, 222}, {"z", 2, 222}},
        {{"Bag", 1, 700}, {"Mug", 3, 1350}},
        {{"x", 10, 50}},
        {{"Same", 1, 200}, {"same", 1, 100}},
        {{"K", 7, 1645}},
    };
    for (std::size_t index = 0; index < cases.size(); index += 1) {
        check(solution(cases[index]), expected[index], "stated case");
        checkRows(cases[index], "stated case reference");
    }
    checkRows({{"M", 1, 1}, {"M", 1, 1}, {"M", 1, 1}}, "repeated product");
    checkRows({{"a", 1, 999}, {"b", 1, 999}, {"a", 1, 1}}, "scattered product");
    checkRows({{"Z", 1000, 100000000}}, "one heavy line");
    checkRows(warehouse(20261017ULL), "warehouse");

    checkRejected({{"", 1, 200}}, "empty product");
    checkRejected({{"na\xc3\xafve", 1, 200}}, "product outside ascii");
    checkRejected({{"Tea", 0, 200}}, "zero quantity");
    checkRejected({{"Tea", -4, 200}}, "negative quantity");
    checkRejected({{"Tea", kMaxCount + 1, 200}}, "quantity above the ceiling");
    checkRejected({{"Tea", 1, -1}}, "negative price");
    checkRejected({{"Tea", 1, kMaxPrice + 1}}, "price above the ceiling");
    checkRejected({{"Tea", 9223372036854775807LL, 9223372036854775807LL}}, "huge row");
    std::vector<SaleRow> lateBad = warehouse(7ULL);
    lateBad.push_back(SaleRow{"Tea", 0, 5});
    checkRejected(lateBad, "invalid row at the end of a large request");

    unsigned long long state = 99ULL;
    const auto next = [&state]() {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return state >> 33;
    };
    for (int round = 0; round < 1500; round += 1) {
        std::vector<SaleRow> rows;
        const int count = static_cast<int>(next() % 7);
        for (int index = 0; index < count; index += 1) {
            const std::string name = "N" + std::to_string(next() % 5);
            rows.push_back(SaleRow{name, 1 + static_cast<long long>(next() % 50),
                                   static_cast<long long>(next() % 4000)});
        }
        checkRows(rows, "random request");
    }
    return 0;
}
