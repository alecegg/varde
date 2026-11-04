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
    const std::size_t slotCount = request.slots.size();
    for (std::size_t slotIndex = 0; slotIndex < slotCount; ++slotIndex) {
        const Slot& slot = request.slots[slotIndex];
        const bool startsInsideDay = slot.start >= 0;
        const bool endsInsideDay = slot.end <= 1440;
        const bool advances = slot.start < slot.end;
        const bool intervalIsValid = startsInsideDay && endsInsideDay && advances;
        if (!intervalIsValid) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    const std::size_t reservationCount = request.reserved.size();
    for (std::size_t reservationIndex = 0; reservationIndex < reservationCount;
         ++reservationIndex) {
        const Reservation& reservation = request.reserved[reservationIndex];
        const bool startsInsideDay = reservation.start >= 0;
        const bool endsInsideDay = reservation.end <= 1440;
        const bool advances = reservation.start < reservation.end;
        const bool intervalIsValid = startsInsideDay && endsInsideDay && advances;
        if (!intervalIsValid) {
            throw std::invalid_argument("invalid_interval");
        }
    }
    std::vector<Slot> availableSlots;
    availableSlots.reserve(request.slots.size());
    for (std::size_t slotIndex = 0; slotIndex < slotCount; ++slotIndex) {
        const Slot& slot = request.slots[slotIndex];
        bool hasOverlap = false;
        for (std::size_t reservationIndex = 0; reservationIndex < reservationCount;
             ++reservationIndex) {
            const Reservation& reservation = request.reserved[reservationIndex];
            const bool beginsBeforeReservationEnds = slot.start < reservation.end;
            const bool reservationBeginsBeforeSlotEnds = reservation.start < slot.end;
            const bool overlaps = beginsBeforeReservationEnds && reservationBeginsBeforeSlotEnds;
            const bool separated = !beginsBeforeReservationEnds || !reservationBeginsBeforeSlotEnds;
            if (overlaps && !separated) {
                hasOverlap = true;
                break;
            }
        }
        if (!hasOverlap) {
            availableSlots.push_back(slot);
        }
    }
    std::sort(availableSlots.begin(), availableSlots.end(),
              [](const Slot& left, const Slot& right) {
                  const int leftStartMinute = left.start;
                  const int rightStartMinute = right.start;
                  if (leftStartMinute < rightStartMinute) {
                      return true;
                  }
                  if (leftStartMinute > rightStartMinute) {
                      return false;
                  }
                  const std::string leftIdentifier = left.id;
                  const std::string rightIdentifier = right.id;
                  return leftIdentifier < rightIdentifier;
              });
    const bool hasAvailableAppointment = !availableSlots.empty();
    if (!hasAvailableAppointment) {
        return {};
    }
    std::vector<std::string> result;
    result.reserve(availableSlots.size());
    for (std::size_t slotIndex = 0; slotIndex < availableSlots.size(); ++slotIndex) {
        const std::string identifier = availableSlots[slotIndex].id;
        result.push_back(identifier);
    }
    return result;
}
