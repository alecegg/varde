#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

struct Slot { std::string id; int start; int end; };
struct Reservation { int start; int end; };
using SlotList = std::vector<Slot>;
using ReservationList = std::vector<Reservation>;
using IdList = std::vector<std::string>;
struct Request { SlotList slots; ReservationList reserved; };

bool slot_interval_valid(const Slot& x) { return x.start >= 0 &&
    x.end <= 1440 && x.start < x.end; }
bool reservation_interval_valid(const Reservation& x) { return x.start >= 0 &&
    x.end <= 1440 && x.start < x.end; }
bool slot_intervals_valid(const Request& x) { return std::all_of(
    x.slots.begin(), x.slots.end(), slot_interval_valid); }
bool reservation_intervals_valid(const Request& x) { return std::all_of(
    x.reserved.begin(), x.reserved.end(), reservation_interval_valid); }
bool request_intervals_valid(const Request& x) {
    return slot_intervals_valid(x) && reservation_intervals_valid(x);
}
bool slot_overlaps_reservation(const Slot& s, const Reservation& r) {
    return s.start < r.end && r.start < s.end;
}
bool slot_has_no_reservation(const Slot& s, const Request& x) { for(auto& r:x.reserved)
    if(slot_overlaps_reservation(s,r))return false;
    return true; }
void append_available_slot(const Slot& s, SlotList& out) { out.push_back(s); }
void append_unreserved_slots(const Request& x, SlotList& out) { for(auto& s:x.slots)
    if(slot_has_no_reservation(s,x))append_available_slot(s,out); }
bool slot_precedes(const Slot& a, const Slot& b) {
    return a.start == b.start ? a.id < b.id : a.start < b.start;
}
SlotList sort_available_slots(SlotList x) {
    std::sort(x.begin(), x.end(), slot_precedes);
    return x; }
IdList ordered_slot_identifiers(const SlotList& x) { IdList identifiers;
    for (auto& s : x) identifiers.push_back(s.id);
    return identifiers; }
SlotList available_slots(const Request& x) { SlotList out;
    append_unreserved_slots(x, out);
    return out; }
const Request* validated_request(const Request& x) { if (!request_intervals_valid(x))
    throw std::invalid_argument("invalid_interval");
    return &x; }

// Return the identifiers of available appointment slots after applying reservation overlap rules.
std::vector<std::string> solution(const Request& request) { return ordered_slot_identifiers(
    sort_available_slots(available_slots(*validated_request(request)))); }
