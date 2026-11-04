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


void validateSlots(const Request& request) {
    for (const Slot& slot : request.slots) {
        if (slot.start < 0 || slot.end > 1440 || slot.start >= slot.end) {
            throw std::invalid_argument("invalid_interval");
        }
    }
}

void validateReservations(const Request& request) {
    for (const Reservation& reservation : request.reserved) {
        if (reservation.start < 0 || reservation.end > 1440 ||
            reservation.start >= reservation.end) {
            throw std::invalid_argument("invalid_interval");
        }
    }
}

std::vector<Slot> available(const Request& request) {
    std::vector<Slot> free;
    for (const Slot& slot : request.slots) {
        bool blocked = false;
        for (const Reservation& reservation : request.reserved) {
            if (slot.start < reservation.end && reservation.start < slot.end) {
                blocked = true;
                break;
            }
        }
        if (!blocked) {
            free.push_back(slot);
        }
    }
    return free;
}

void orderSlots(std::vector<Slot>& slots) {
    std::sort(slots.begin(), slots.end(), [](const Slot& left, const Slot& right) {
        if (left.start != right.start) {
            return left.start < right.start;
        }
        return left.id < right.id;
    });
}

std::vector<std::string> identifiers(const std::vector<Slot>& slots) {
    std::vector<std::string> ids;
    ids.reserve(slots.size());
    for (const Slot& slot : slots) {
        ids.push_back(slot.id);
    }
    return ids;
}

// Return the identifiers of available appointment slots after applying reservation overlap rules.
std::vector<std::string> solution(const Request& request) {
    validateSlots(request);
    validateReservations(request);
    std::vector<Slot> free = available(request);
    orderSlots(free);
    return identifiers(free);
}

