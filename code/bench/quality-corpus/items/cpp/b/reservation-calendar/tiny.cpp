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

bool slot_ok(const Slot& x) { return x.start >= 0 && x.end <= 1440 && x.start < x.end; }
bool res_ok(const Reservation& x) { return x.start >= 0 && x.end <= 1440 && x.start < x.end; }
bool slots_ok(const Request& x) {
    return std::all_of(x.slots.begin(), x.slots.end(), slot_ok);
}
bool reses_ok(const Request& x) {
    return std::all_of(x.reserved.begin(), x.reserved.end(), res_ok);
}
bool all_ok(const Request& x) { return slots_ok(x) && reses_ok(x); }
bool hit(const Slot& s, const Reservation& r) { return s.start < r.end && r.start < s.end; }
bool clear(const Slot& s, const Request& x) { for(auto& r:x.reserved)if(hit(s,r))return false;
    return true; }
void take(const Slot& s, SlotList& out) { out.push_back(s); }
void visit(const Request& x, SlotList& out) {
    for(auto& s:x.slots)if(clear(s,x))take(s,out);
}
bool less_id(const Slot& a, const Slot& b) { return a.start == b.start
    ? a.id < b.id : a.start < b.start; }
using Ids = IdList;
Ids names(const SlotList& x) { Ids out;
    for(auto& s:x)out.push_back(s.id);
    return out; }
SlotList collect(const Request& x) { SlotList out;
    visit(x, out);
    return out; }
const Request* checked(const Request& x) { if (!all_ok(x))
    throw std::invalid_argument("invalid_interval");
    return &x; }
SlotList ordered(SlotList x) { std::sort(x.begin(), x.end(), less_id);
    return x; }

// Return the identifiers of available appointment slots after applying reservation overlap rules.
std::vector<std::string> solution(const Request& request) {
    return names(ordered(collect(*checked(request))));
}
