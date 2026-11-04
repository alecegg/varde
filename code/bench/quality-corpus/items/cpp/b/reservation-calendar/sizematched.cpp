#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

struct Slot {
    std::string id;
    int start;
    int end;
};

struct Reservation {
    int start;
    int end;
};

struct Request {
    std::vector<Slot> slots;
    std::vector<Reservation> reserved;
};

// Return the identifiers of available appointment slots after applying reservation overlap rules.
std::vector<std::string> solution(const Request& request) {
    std::vector<Slot> free;
    free.reserve(request.slots.size());
    for (const Slot& slot : request.slots) {
        const bool beginsWithinDay = slot.start >= 0;
        const bool finishesWithinDay = slot.end <= 1440;
        const bool hasPositiveDuration = slot.start < slot.end;
        const bool isValid = beginsWithinDay && finishesWithinDay && hasPositiveDuration;
        if (!isValid) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    for (const Reservation& reservation : request.reserved) {
        const bool beginsWithinDay = reservation.start >= 0;
        const bool finishesWithinDay = reservation.end <= 1440;
        const bool hasPositiveDuration = reservation.start < reservation.end;
        const bool isValid = beginsWithinDay && finishesWithinDay && hasPositiveDuration;
        if (!isValid) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    if (request.slots.empty()) {
        return {};
    }
    for (const Slot& slot : request.slots) {
        bool hasOverlap = false;
        for (const Reservation& reservation : request.reserved) {
            const bool slotStartsBeforeReservationEnds = slot.start < reservation.end;
            const bool reservationStartsBeforeSlotEnds = reservation.start < slot.end;
            const bool intervalsOverlap = slotStartsBeforeReservationEnds &&
                                          reservationStartsBeforeSlotEnds;
            if (intervalsOverlap) {
                hasOverlap = true;
                break;
            }
        }
        if (!hasOverlap) {
            free.push_back(slot);
        }
    }
    std::sort(free.begin(), free.end(), [](const Slot& left, const Slot& right) {
        if (left.start != right.start) {
            return left.start < right.start;
        }
        const std::string leftIdentifier = left.id;
        const std::string rightIdentifier = right.id;
        return leftIdentifier < rightIdentifier;
    });
    std::vector<std::string> ids;
    ids.reserve(free.size());
    for (const Slot& slot : free) {
        ids.push_back(slot.id);
    }
    return ids;
}
