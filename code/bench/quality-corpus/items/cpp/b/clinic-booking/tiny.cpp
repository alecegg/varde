#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

using Minutes = std::int64_t;
using Index = std::size_t;

struct Window {
    Minutes weekday;
    Minutes open;
    Minutes close;
};

struct Doctor {
    std::string name;
    std::vector<Window> windows;
};

struct Booking {
    Minutes day;
    Minutes start;
    Minutes end;
    std::string doctor;
};

struct Request {
    Minutes now_day;
    Minutes now_minute;
    Minutes requested_day;
    Minutes horizon_days;
    std::string kind;
    bool urgent;
    std::string preferred_doctor;
    std::vector<Minutes> holidays;
    std::vector<Doctor> doctors;
    std::vector<Booking> bookings;
};

struct Slot {
    Minutes day;
    Minutes start;
    Minutes end;
    std::string doctor;
    std::vector<std::string> trace;
};

struct Failure {
    std::string code;
    bool has_index;
    Minutes index;
};

struct Outcome {
    bool failed;
    Failure error;
    Slot slot;
};

struct Entry {
    std::string name;
    std::string key;
    std::vector<Window> windows;
};

struct Visit {
    Minutes day;
    Minutes start;
    Minutes end;
    std::string key;
};

struct Normalised {
    std::string kind;
    std::string preferred;
    std::vector<Entry> doctors;
    std::vector<Visit> bookings;
};

struct Rules {
    Minutes duration;
    Minutes buffer;
};

struct Candidate {
    Minutes day;
    Minutes start;
    Minutes end;
    std::string key;
    std::string doctor;
};

struct Plan {
    const Request& request;
    const Normalised& normal;
    Rules rules;
    Minutes day;
};

struct Rejection {
    Failure failure;
};

constexpr Minutes kMaxDay = 1000000;

constexpr Index kMaxDoctors = 12;

constexpr const char* kNameLetters =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -";

const Failure kNoFailure{"", false, 0};

const std::vector<std::string> kTrace = {
    "normalised",      "validated",           "holiday-filter",   "hours-and-lunch",
    "notice",          "doctor-availability", "daily-cap",        "booking-conflicts",
    "urgent-priority", "earliest-grid-slot"};

Index startOf(const std::string& text) {
    Index lead = 0;
    while (lead < text.size() && text[lead] == ' ') { lead += 1; }
    return lead;
}

Index stopOf(const std::string& text, Index lead) {
    Index end = text.size();
    while (end > lead && text[end - 1] == ' ') { end -= 1; }
    return end;
}

std::string cut(const std::string& text) {
    const Index lead = startOf(text);
    return text.substr(lead, stopOf(text, lead) - lead);
}

std::string low(const std::string& text) {
    std::string out = text;
    for (char& letter : out) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return out;
}

Failure plain(const char* code) {
    return Failure{code, false, 0};
}

Failure at(const char* code, Index position) {
    return Failure{code, true, static_cast<Minutes>(position)};
}

Rules ruleOf(const std::string& kind) {
    if (kind == "consultation") { return Rules{30, 10}; }
    if (kind == "procedure") { return Rules{60, 15}; }
    return Rules{20, 5};
}

Entry entryOf(const Doctor& doctor) {
    const std::string name = cut(doctor.name);
    return Entry{name, low(name), doctor.windows};
}

std::vector<Entry> entries(const std::vector<Doctor>& doctors) {
    std::vector<Entry> out;
    for (const Doctor& doctor : doctors) { out.push_back(entryOf(doctor)); }
    return out;
}

Visit visitOf(const Booking& booking) {
    return Visit{booking.day, booking.start, booking.end, low(cut(booking.doctor))};
}

std::vector<Visit> visits(const std::vector<Booking>& bookings) {
    std::vector<Visit> out;
    for (const Booking& booking : bookings) { out.push_back(visitOf(booking)); }
    return out;
}

Normalised normalise(const Request& request) {
    Normalised normal;
    normal.kind = low(cut(request.kind));
    normal.preferred = low(cut(request.preferred_doctor));
    normal.doctors = entries(request.doctors);
    normal.bookings = visits(request.bookings);
    return normal;
}

bool daysFit(const Request& request) {
    const bool now_ok = request.now_day >= 0 && request.now_day <= kMaxDay;
    const bool day_ok = request.requested_day >= 0 && request.requested_day <= kMaxDay;
    return now_ok && day_ok;
}

bool timeFit(const Request& request) {
    const bool minute_ok = request.now_minute >= 0 && request.now_minute <= 1439;
    const bool horizon_ok = request.horizon_days >= 0 && request.horizon_days <= 14;
    return minute_ok && horizon_ok;
}

bool kindKnown(const Normalised& normal) {
    return normal.kind == "checkup" || normal.kind == "consultation" ||
           normal.kind == "procedure";
}

bool scalarsOk(const Request& request, const Normalised& normal) {
    return daysFit(request) && timeFit(request) && kindKnown(normal);
}

void checkScalars(const Request& request, const Normalised& normal) {
    if (!scalarsOk(request, normal)) { throw Rejection{plain("BAD_REQUEST")}; }
}

bool shaped(const std::string& name) {
    if (name.empty()) { return false; }
    return name.find_first_not_of(kNameLetters) == std::string::npos;
}

bool repeats(const Normalised& normal, Index position) {
    const std::string& key = normal.doctors[position].key;
    for (Index earlier = 0; earlier < position; ++earlier) {
        if (normal.doctors[earlier].key == key) { return true; }
    }
    return false;
}

bool doctorOk(const Normalised& normal, Index position) {
    return shaped(normal.doctors[position].name) && !repeats(normal, position);
}

void checkDoctor(const Normalised& normal, Index position) {
    if (!doctorOk(normal, position)) {
        throw Rejection{at("BAD_DOCTORS", position)};
    }
}

void checkDoctors(const Normalised& normal) {
    if (normal.doctors.empty() || normal.doctors.size() > kMaxDoctors) {
        throw Rejection{plain("BAD_DOCTORS")};
    }
    for (Index position = 0; position < normal.doctors.size(); position += 1) {
        checkDoctor(normal, position);
    }
}

bool windowOk(const Window& window) {
    const bool day_ok = window.weekday >= 0 && window.weekday <= 6;
    const bool hours_ok = window.open >= 0 && window.open < window.close;
    return day_ok && hours_ok && window.close <= 1440;
}

bool badWindows(const Entry& doctor) {
    if (doctor.windows.size() > 8) { return true; }
    for (const Window& window : doctor.windows) {
        if (!windowOk(window)) { return true; }
    }
    return false;
}

void checkWindow(const Normalised& normal, Index position) {
    if (badWindows(normal.doctors[position])) {
        throw Rejection{at("BAD_WINDOW", position)};
    }
}

void checkWindows(const Normalised& normal) {
    for (Index position = 0; position < normal.doctors.size(); position += 1) {
        checkWindow(normal, position);
    }
}

bool dayRepeat(const std::vector<Minutes>& days, Index position) {
    const Minutes day = days[position];
    return std::find(days.begin(), days.begin() + position, day) != days.begin() + position;
}

bool dayOk(const std::vector<Minutes>& days, Index position) {
    const Minutes day = days[position];
    return day >= 0 && day <= kMaxDay && !dayRepeat(days, position);
}

void checkHolidays(const Request& request) {
    if (request.holidays.size() > 60) { throw Rejection{plain("BAD_HOLIDAY")}; }
    for (Index position = 0; position < request.holidays.size(); position += 1) {
        if (!dayOk(request.holidays, position)) {
            throw Rejection{at("BAD_HOLIDAY", position)};
        }
    }
}

bool listsKey(const Normalised& normal, const std::string& key) {
    for (const Entry& doctor : normal.doctors) {
        if (doctor.key == key) { return true; }
    }
    return false;
}

bool visitOk(const Normalised& normal, const Visit& visit) {
    const bool day_ok = visit.day >= 0 && visit.day <= kMaxDay;
    const bool hours_ok = visit.start >= 0 && visit.start < visit.end;
    return day_ok && hours_ok && visit.end <= 1440 && listsKey(normal, visit.key);
}

void checkVisit(const Normalised& normal, Index position) {
    if (!visitOk(normal, normal.bookings[position])) {
        throw Rejection{at("BAD_BOOKING", position)};
    }
}

void checkBookings(const Normalised& normal) {
    if (normal.bookings.size() > 200) { throw Rejection{plain("BAD_BOOKING")}; }
    for (Index position = 0; position < normal.bookings.size(); position += 1) {
        checkVisit(normal, position);
    }
}

void checkPreferred(const Normalised& normal) {
    if (!normal.preferred.empty() && !listsKey(normal, normal.preferred)) {
        throw Rejection{plain("UNKNOWN_DOCTOR")};
    }
}

bool ordered(const Request& request) {
    const bool ahead = request.requested_day >= request.now_day;
    const bool near = request.requested_day - request.now_day <= 8;
    return ahead && near;
}

void checkOrder(const Request& request) {
    if (!ordered(request)) { throw Rejection{plain("BAD_DAY_ORDER")}; }
}

void checkAll(const Request& request, const Normalised& normal) {
    checkScalars(request, normal);
    checkDoctors(normal);
    checkWindows(normal);
    checkHolidays(request);
    checkBookings(normal);
    checkPreferred(normal);
    checkOrder(request);
}

bool hasCode(const Failure& failure) {
    return !failure.code.empty();
}

Failure firstFailure(const Request& request, const Normalised& normal) {
    try {
        checkAll(request, normal);
    } catch (const Rejection& rejection) {
        return rejection.failure;
    }
    return kNoFailure;
}

Minutes endOf(const Candidate& row, const Rules& rules) {
    return row.end + rules.buffer;
}

bool withinHours(Minutes weekday, const Candidate& row, Minutes reserved_end) {
    const Minutes open = weekday == 5 ? 600 : 540;
    const Minutes close = weekday == 5 ? 840 : 1020;
    return weekday != 6 && row.start >= open && reserved_end <= close;
}

bool offLunch(const Candidate& row, Minutes reserved_end) {
    return !(row.start < 780 && reserved_end > 720);
}

bool windowHolds(const Entry& doctor, Minutes weekday, const Candidate& row,
                 Minutes reserved_end) {
    for (const Window& window : doctor.windows) {
        if (window.weekday == weekday && window.open <= row.start &&
            reserved_end <= window.close) {
            return true;
        }
    }
    return false;
}

bool hoursAdmit(const Entry& doctor, const Candidate& row, Minutes reserved_end) {
    const Minutes weekday = row.day % 7;
    if (!withinHours(weekday, row, reserved_end)) { return false; }
    if (!offLunch(row, reserved_end)) { return false; }
    return windowHolds(doctor, weekday, row, reserved_end);
}

bool overlaps(const Visit& visit, const Candidate& row, Minutes reserved_end) {
    return row.start < visit.end && visit.start < reserved_end;
}

bool clashes(const std::vector<Visit>& visits, const Candidate& row,
             Minutes reserved_end) {
    for (const Visit& visit : visits) {
        if (visit.day != row.day || visit.key != row.key) { continue; }
        if (overlaps(visit, row, reserved_end)) { return true; }
    }
    return false;
}

bool earlyEnough(const Plan& plan, const Candidate& row) {
    if (row.day != plan.request.now_day) { return true; }
    return row.start >= plan.request.now_minute + 60;
}

bool slotAdmits(const Plan& plan, const Entry& doctor, const Candidate& row) {
    const Minutes reserved_end = endOf(row, plan.rules);
    if (!earlyEnough(plan, row)) { return false; }
    if (!hoursAdmit(doctor, row, reserved_end)) { return false; }
    return !clashes(plan.normal.bookings, row, reserved_end);
}

bool wanted(const Plan& plan, const std::string& key) {
    if (plan.request.urgent || plan.normal.preferred.empty()) { return true; }
    return key == plan.normal.preferred;
}

Minutes loadOn(const Plan& plan, const Entry& doctor) {
    Minutes count = 0;
    for (const Visit& visit : plan.normal.bookings) {
        if (visit.day == plan.day && visit.key == doctor.key) { count += 1; }
    }
    return count;
}

bool underCap(const Plan& plan, const Entry& doctor) {
    if (!wanted(plan, doctor.key)) { return false; }
    return loadOn(plan, doctor) < 4;
}

bool closed(const std::vector<Minutes>& holidays, Minutes day) {
    return std::find(holidays.begin(), holidays.end(), day) != holidays.end();
}

Minutes lastDay(const Request& request) {
    return std::min({request.requested_day + request.horizon_days,
                     request.requested_day + 14, kMaxDay});
}

std::vector<Minutes> openDays(const Request& request) {
    const Minutes last = lastDay(request);
    std::vector<Minutes> days;
    for (Minutes day = request.requested_day; day <= last; day += 1) {
        if (!closed(request.holidays, day)) { days.push_back(day); }
    }
    return days;
}

Candidate seed(const Plan& plan, const Entry& doctor, Minutes start) {
    return Candidate{plan.day, start, start + plan.rules.duration, doctor.key, doctor.name};
}

void scanStarts(std::vector<Candidate>& out, const Plan& plan, const Entry& doctor) {
    for (Minutes start = 0; start <= 1435; start += 5) {
        const Candidate row = seed(plan, doctor, start);
        if (slotAdmits(plan, doctor, row)) { out.push_back(row); }
    }
}

void daySlots(std::vector<Candidate>& out, const Plan& plan) {
    for (const Entry& doctor : plan.normal.doctors) {
        if (underCap(plan, doctor)) { scanStarts(out, plan, doctor); }
    }
}

std::vector<Candidate> gather(const Request& request, const Normalised& normal,
                              const Rules& rules) {
    std::vector<Candidate> found;
    for (const Minutes day : openDays(request)) {
        daySlots(found, Plan{request, normal, rules, day});
    }
    return found;
}

std::vector<Candidate> offered(const Request& request, const Normalised& normal,
                               const Rules& rules) {
    return gather(request, normal, rules);
}

bool sooner(const Candidate& row, const Candidate& best) {
    if (row.day != best.day) { return row.day < best.day; }
    if (row.start != best.start) { return row.start < best.start; }
    return row.key < best.key;
}

const Candidate* first(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) { return nullptr; }
    const Candidate* best = &candidates.front();
    for (const Candidate& row : candidates) {
        if (sooner(row, *best)) { best = &row; }
    }
    return best;
}

Slot packed(const Candidate& best) {
    return Slot{best.day, best.start, best.end, best.doctor, kTrace};
}

Outcome rejected(const Failure& failure) {
    return Outcome{true, failure, Slot{}};
}

Outcome empty() {
    return rejected(plain("NO_SLOT"));
}

Outcome choose(const std::vector<Candidate>& candidates) {
    const Candidate* best = first(candidates);
    if (best == nullptr) { return empty(); }
    return Outcome{false, kNoFailure, packed(*best)};
}

Outcome pick(const std::vector<Candidate>& candidates) {
    return choose(candidates);
}

/** Return the earliest valid appointment or the first validation error. */
Outcome solution(const Request& request) {
    const Normalised normal = normalise(request);
    const Failure failure = firstFailure(request, normal);
    if (hasCode(failure)) { return rejected(failure); }
    const Rules rules = ruleOf(normal.kind);
    return pick(offered(request, normal, rules));
}
