#include <algorithm>
#include <stdexcept>
#include <utility>
#include <string>
#include <vector>

struct Slot { std::string id; int start; int end; };
struct Reservation { int start; int end; };
struct Request { std::vector<Slot> slots; std::vector<Reservation> reserved; };

bool slot_bounds_are_valid(const Slot& slot) {
    const bool starts_after_midnight = slot.start >= 0;
    const bool ends_before_day_close = slot.end <= 1440;
    const bool has_positive_duration = slot.start < slot.end;
    return starts_after_midnight && ends_before_day_close && has_positive_duration;
}
bool reservation_bounds_are_valid(const Reservation& reservation) {
    const bool starts_after_midnight = reservation.start >= 0;
    const bool ends_before_day_close = reservation.end <= 1440;
    const bool has_positive_duration = reservation.start < reservation.end;
    return starts_after_midnight && ends_before_day_close && has_positive_duration;
}
bool slot_collection_is_valid(const Request& request) {
    return std::all_of(request.slots.begin(), request.slots.end(), slot_bounds_are_valid);
}
bool reservation_collection_is_valid(const Request& request) { return std::all_of(
    request.reserved.begin(), request.reserved.end(), reservation_bounds_are_valid); }
bool calendar_is_valid(const Request& request) {
    const bool every_slot_is_valid = slot_collection_is_valid(request);
    const bool every_reservation_is_valid = reservation_collection_is_valid(request);
    return every_slot_is_valid && every_reservation_is_valid;
}
bool intervals_share_time(const Slot& slot, const Reservation& reservation) {
    const bool slot_begins_before_reservation_finishes = slot.start < reservation.end;
    const bool reservation_begins_before_slot_finishes = reservation.start < slot.end;
    return slot_begins_before_reservation_finishes && reservation_begins_before_slot_finishes;
}
bool no_reservation_overlaps(const Slot& slot, const Request& request) {
    for (const Reservation& reservation : request.reserved) {
        const bool blocked = intervals_share_time(slot, reservation);
        if (blocked) return false;
    }
    return true;
}
void save_available_slot(const Slot& slot, std::vector<Slot>& available) {
    if (available.size() == available.capacity()) {
        const std::size_t next_capacity = available.capacity() == 0 ? 1 : available.capacity() * 2;
        available.reserve(next_capacity);
    }
    available.push_back(slot);
}
void find_available_slots(const Request& request, std::vector<Slot>& available) {
    for (const Slot& slot : request.slots) {
        const bool unreserved = no_reservation_overlaps(slot, request);
        if (unreserved) save_available_slot(slot, available);
    }
}
std::vector<Slot> collect_available_slots(const Request& request) {
    std::vector<Slot> available;
    find_available_slots(request, available);
    return available;
}
bool earlier_in_order(const Slot& first, const Slot& second) {
    if (first.start != second.start) return first.start < second.start;
    const bool identifier_comes_first = first.id < second.id;
    return identifier_comes_first;
}
std::vector<Slot> chronologically_ordered(std::vector<Slot> available) {
    std::sort(available.begin(), available.end(), earlier_in_order);
    return available;
}
std::vector<std::string> collect_slot_ids(const std::vector<Slot>& available) {
    std::vector<std::string> ids;
    ids.reserve(available.size());
    for (const Slot& slot : available) ids.push_back(slot.id);
    return ids;
}
const Request* checked_calendar(const Request& request) {
    if (!calendar_is_valid(request)) throw std::invalid_argument("invalid_interval");
    return &request;
}

// Return the identifiers of available appointment slots after applying reservation overlap rules.
std::vector<std::string> solution(const Request& request) {
    return collect_slot_ids(chronologically_ordered(
        collect_available_slots(*checked_calendar(request))));
}
