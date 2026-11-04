#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "solution.cpp"

std::vector<std::string> reference(const Request& request) {
    for (const Slot& slot : request.slots) {
        if (slot.start < 0 || slot.end > 1440 || slot.start >= slot.end) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    for (const Reservation& reserved : request.reserved) {
        if (reserved.start < 0 || reserved.end > 1440 || reserved.start >= reserved.end) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    std::vector<const Slot*> available;
    for (const Slot& slot : request.slots) {
        bool overlaps = false;
        for (const Reservation& reserved : request.reserved) {
            const bool separated = slot.end <= reserved.start || reserved.end <= slot.start;
            if (!separated) {
                overlaps = true;
                break;
            }
        }
        if (!overlaps) {
            available.push_back(&slot);
        }
    }
    std::sort(available.begin(), available.end(), [](const Slot* left, const Slot* right) {
        if (left->start != right->start) {
            return left->start < right->start;
        }
        return left->id < right->id;
    });
    std::vector<std::string> ids;
    for (const Slot* slot : available) {
        ids.push_back(slot->id);
    }
    return ids;
}

void check(const Request& request, const std::vector<std::string>& expected, const char* label) {
    try {
        const std::vector<std::string> got = solution(request);
        if (got == expected) {
            return;
        }
    } catch (const std::invalid_argument& error) {
        std::cerr << label << ": unexpected rejection " << error.what() << '\n';
        std::exit(1);
    }
    std::cerr << label << ": result differs from expected ids\n";
    std::exit(1);
}

void checkReference(const Request& request, const char* label) {
    try {
        check(request, reference(request), label);
    } catch (const std::invalid_argument& error) {
        if (std::string(error.what()) == "invalid_interval") {
            try {
                (void)solution(request);
                std::cerr << label << ": expected invalid_interval\n";
                std::exit(1);
            } catch (const std::invalid_argument& actual) {
                if (std::string(actual.what()) != "invalid_interval") {
                    std::cerr << label << ": wrong error " << actual.what() << '\n';
                    std::exit(1);
                }
            }
            return;
        }
        throw;
    }
}

Request largeCalendar() {
    Request request;
    request.slots.reserve(3000);
    for (int index = 0; index < 3000; ++index) {
        const int start = (index * 37) % 1440;
        const int finish = std::min(1440, start + 1 + (index % 60));
        request.slots.push_back(Slot{"slot" + std::to_string(2999 - index), start, finish});
    }
    for (int index = 0; index < 120; ++index) {
        const int start = (index * 53) % 1430;
        request.reserved.push_back(Reservation{start, start + 1 + index % 10});
    }
    return request;
}

int main() {
    const std::vector<std::pair<Request, std::vector<std::string>>> cases = {
        {Request{}, {}},
        {Request{{{"A", 540, 600}}, {}}, {"A"}},
        {Request{{{"A", 540, 600}}, {{540, 600}}}, {}},
        {Request{{{"A", 480, 540}, {"B", 540, 600}}, {{540, 570}}}, {"A"}},
        {Request{{{"A", 540, 600}}, {{570, 630}}}, {}},
        {Request{{{"B", 600, 660}, {"A", 540, 600}}, {{700, 720}}}, {"A", "B"}},
        {Request{{{"b", 540, 600}, {"A", 540, 600}, {"a", 540, 600}, {"B", 540, 600}}, {}},
         {"A", "B", "a", "b"}},
        {Request{{{"early", 0, 30}, {"late", 1410, 1440}}, {{30, 60}}}, {"early", "late"}},
        {Request{{{"end", 1439, 1440}, {"start", 0, 1}}, {}}, {"start", "end"}},
    };
    for (const auto& [request, expected] : cases) {
        check(request, expected, "bank case");
        checkReference(request, "bank case reference");
    }
    checkReference(largeCalendar(), "large calendar");
    checkReference(Request{{{"bad", 600, 600}}, {}}, "empty slot interval");
    checkReference(Request{{{"bad", 601, 600}}, {}}, "reversed slot interval");
    checkReference(Request{{{"ok", 0, 1}}, {{1440, 1440}}}, "empty reservation");
    checkReference(Request{{{"bad", -1, 2}}, {}}, "slot before day");
    checkReference(Request{{{"bad", 1439, 1441}}, {}}, "slot after day");
    checkReference(Request{{{"ok", 0, 1}}, {{-1, 2}}}, "reservation before day");
    checkReference(Request{{{"ok", 0, 1}}, {{1439, 1441}}}, "reservation after day");
    unsigned int state = 20261017U;
    for (int round = 0; round < 1200; ++round) {
        state = state * 1664525U + 1013904223U;
        Request request;
        const int count = static_cast<int>(state % 8U);
        for (int index = 0; index < count; ++index) {
            state = state * 1664525U + 1013904223U;
            const int start = static_cast<int>(state % 1440U);
            const int end = start + 1 + static_cast<int>((state >> 10U) % (1440U - static_cast<unsigned int>(start)));
            request.slots.push_back(Slot{"id" + std::to_string((state >> 5U) % 9U), start, end});
            state = state * 1664525U + 1013904223U;
            const int reservedStart = static_cast<int>(state % 1440U);
            const int reservedEnd = reservedStart + 1 + static_cast<int>((state >> 11U) % (1440U - static_cast<unsigned int>(reservedStart)));
            request.reserved.push_back(Reservation{reservedStart, reservedEnd});
        }
        checkReference(request, "random calendar");
    }
    return 0;
}
