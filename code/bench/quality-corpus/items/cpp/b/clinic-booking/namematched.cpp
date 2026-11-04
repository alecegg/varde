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

Index firstNonSpace(const std::string& text) {
    Index lead = 0;
    while (lead < text.size() && text[lead] == ' ') { lead += 1; }
    return lead;
}

Index lastNonSpace(const std::string& text, Index lead) {
    Index end = text.size();
    while (end > lead && text[end - 1] == ' ') { end -= 1; }
    return end;
}

std::string trimSpaces(const std::string& text) {
    const Index lead = firstNonSpace(text);
    return text.substr(lead, lastNonSpace(text, lead) - lead);
}

std::string lowerAscii(const std::string& text) {
    std::string out = text;
    for (char& letter : out) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return out;
}

Failure plainFailure(const char* code) {
    return Failure{code, false, 0};
}

Failure indexedFailure(const char* code, Index position) {
    return Failure{code, true, static_cast<Minutes>(position)};
}

Rules rulesFor(const std::string& kind) {
    if (kind == "consultation") { return Rules{30, 10}; }
    if (kind == "procedure") { return Rules{60, 15}; }
    return Rules{20, 5};
}

Entry normalEntry(const Doctor& doctor) {
    const std::string name = trimSpaces(doctor.name);
    return Entry{name, lowerAscii(name), doctor.windows};
}

std::vector<Entry> normalEntries(const std::vector<Doctor>& doctors) {
    std::vector<Entry> out;
    for (const Doctor& doctor : doctors) { out.push_back(normalEntry(doctor)); }
    return out;
}

Visit normalVisit(const Booking& booking) {
    return Visit{booking.day, booking.start, booking.end, lowerAscii(trimSpaces(booking.doctor))};
}

std::vector<Visit> normalVisits(const std::vector<Booking>& bookings) {
    std::vector<Visit> out;
    for (const Booking& booking : bookings) { out.push_back(normalVisit(booking)); }
    return out;
}

Normalised normalisedRequest(const Request& request) {
    Normalised normal;
    normal.kind = lowerAscii(trimSpaces(request.kind));
    normal.preferred = lowerAscii(trimSpaces(request.preferred_doctor));
    normal.doctors = normalEntries(request.doctors);
    normal.bookings = normalVisits(request.bookings);
    return normal;
}

bool daysInRange(const Request& request) {
    const bool now_ok = request.now_day >= 0 && request.now_day <= kMaxDay;
    const bool day_ok = request.requested_day >= 0 && request.requested_day <= kMaxDay;
    return now_ok && day_ok;
}

bool timesInRange(const Request& request) {
    const bool minute_ok = request.now_minute >= 0 && request.now_minute <= 1439;
    const bool horizon_ok = request.horizon_days >= 0 && request.horizon_days <= 14;
    return minute_ok && horizon_ok;
}

bool kindRecognised(const Normalised& normal) {
    return normal.kind == "checkup" || normal.kind == "consultation" ||
           normal.kind == "procedure";
}

bool scalarsAcceptable(const Request& request, const Normalised& normal) {
    return daysInRange(request) && timesInRange(request) && kindRecognised(normal);
}

void checkScalarBounds(const Request& request, const Normalised& normal) {
    if (!scalarsAcceptable(request, normal)) { throw Rejection{plainFailure("BAD_REQUEST")}; }
}

bool nameShaped(const std::string& name) {
    if (name.empty()) { return false; }
    return name.find_first_not_of(kNameLetters) == std::string::npos;
}

bool duplicateDoctorName(const Normalised& normal, Index position) {
    const std::string& key = normal.doctors[position].key;
    for (Index earlier = 0; earlier < position; ++earlier) {
        if (normal.doctors[earlier].key == key) { return true; }
    }
    return false;
}

bool doctorAcceptable(const Normalised& normal, Index position) {
    return nameShaped(normal.doctors[position].name) && !duplicateDoctorName(normal, position);
}

void checkOneDoctor(const Normalised& normal, Index position) {
    if (!doctorAcceptable(normal, position)) {
        throw Rejection{indexedFailure("BAD_DOCTORS", position)};
    }
}

void checkDoctorList(const Normalised& normal) {
    if (normal.doctors.empty() || normal.doctors.size() > kMaxDoctors) {
        throw Rejection{plainFailure("BAD_DOCTORS")};
    }
    for (Index position = 0; position < normal.doctors.size(); position += 1) {
        checkOneDoctor(normal, position);
    }
}

bool windowInBounds(const Window& window) {
    const bool day_ok = window.weekday >= 0 && window.weekday <= 6;
    const bool hours_ok = window.open >= 0 && window.open < window.close;
    return day_ok && hours_ok && window.close <= 1440;
}

bool windowsInvalid(const Entry& doctor) {
    if (doctor.windows.size() > 8) { return true; }
    for (const Window& window : doctor.windows) {
        if (!windowInBounds(window)) { return true; }
    }
    return false;
}

void checkOneWindow(const Normalised& normal, Index position) {
    if (windowsInvalid(normal.doctors[position])) {
        throw Rejection{indexedFailure("BAD_WINDOW", position)};
    }
}

void checkWindowList(const Normalised& normal) {
    for (Index position = 0; position < normal.doctors.size(); position += 1) {
        checkOneWindow(normal, position);
    }
}

bool duplicateHoliday(const std::vector<Minutes>& days, Index position) {
    const Minutes day = days[position];
    return std::find(days.begin(), days.begin() + position, day) != days.begin() + position;
}

bool holidayAcceptable(const std::vector<Minutes>& days, Index position) {
    const Minutes day = days[position];
    return day >= 0 && day <= kMaxDay && !duplicateHoliday(days, position);
}

void checkHolidayList(const Request& request) {
    if (request.holidays.size() > 60) { throw Rejection{plainFailure("BAD_HOLIDAY")}; }
    for (Index position = 0; position < request.holidays.size(); position += 1) {
        if (!holidayAcceptable(request.holidays, position)) {
            throw Rejection{indexedFailure("BAD_HOLIDAY", position)};
        }
    }
}

bool namesDoctor(const Normalised& normal, const std::string& key) {
    for (const Entry& doctor : normal.doctors) {
        if (doctor.key == key) { return true; }
    }
    return false;
}

bool bookingAcceptable(const Normalised& normal, const Visit& visit) {
    const bool day_ok = visit.day >= 0 && visit.day <= kMaxDay;
    const bool hours_ok = visit.start >= 0 && visit.start < visit.end;
    return day_ok && hours_ok && visit.end <= 1440 && namesDoctor(normal, visit.key);
}

void checkOneBooking(const Normalised& normal, Index position) {
    if (!bookingAcceptable(normal, normal.bookings[position])) {
        throw Rejection{indexedFailure("BAD_BOOKING", position)};
    }
}

void checkBookingList(const Normalised& normal) {
    if (normal.bookings.size() > 200) { throw Rejection{plainFailure("BAD_BOOKING")}; }
    for (Index position = 0; position < normal.bookings.size(); position += 1) {
        checkOneBooking(normal, position);
    }
}

void checkPreferredDoctor(const Normalised& normal) {
    if (!normal.preferred.empty() && !namesDoctor(normal, normal.preferred)) {
        throw Rejection{plainFailure("UNKNOWN_DOCTOR")};
    }
}

bool dayOrdered(const Request& request) {
    const bool ahead = request.requested_day >= request.now_day;
    const bool near = request.requested_day - request.now_day <= 8;
    return ahead && near;
}

void checkDayOrder(const Request& request) {
    if (!dayOrdered(request)) { throw Rejection{plainFailure("BAD_DAY_ORDER")}; }
}

void checkRequest(const Request& request, const Normalised& normal) {
    checkScalarBounds(request, normal);
    checkDoctorList(normal);
    checkWindowList(normal);
    checkHolidayList(request);
    checkBookingList(normal);
    checkPreferredDoctor(normal);
    checkDayOrder(request);
}

bool failurePresent(const Failure& failure) {
    return !failure.code.empty();
}

Failure validationFailure(const Request& request, const Normalised& normal) {
    try {
        checkRequest(request, normal);
    } catch (const Rejection& rejection) {
        return rejection.failure;
    }
    return kNoFailure;
}

Minutes reservedEnd(const Candidate& row, const Rules& rules) {
    return row.end + rules.buffer;
}

bool insideOpeningHours(Minutes weekday, const Candidate& row, Minutes reserved_end) {
    const Minutes open = weekday == 5 ? 600 : 540;
    const Minutes close = weekday == 5 ? 840 : 1020;
    return weekday != 6 && row.start >= open && reserved_end <= close;
}

bool clearsLunch(const Candidate& row, Minutes reserved_end) {
    return !(row.start < 780 && reserved_end > 720);
}

bool windowAdmits(const Entry& doctor, Minutes weekday, const Candidate& row,
                 Minutes reserved_end) {
    for (const Window& window : doctor.windows) {
        if (window.weekday == weekday && window.open <= row.start &&
            reserved_end <= window.close) {
            return true;
        }
    }
    return false;
}

bool openingAdmits(const Entry& doctor, const Candidate& row, Minutes reserved_end) {
    const Minutes weekday = row.day % 7;
    if (!insideOpeningHours(weekday, row, reserved_end)) { return false; }
    if (!clearsLunch(row, reserved_end)) { return false; }
    return windowAdmits(doctor, weekday, row, reserved_end);
}

bool spansSlot(const Visit& visit, const Candidate& row, Minutes reserved_end) {
    return row.start < visit.end && visit.start < reserved_end;
}

bool bookingConflict(const std::vector<Visit>& normalVisits, const Candidate& row,
             Minutes reserved_end) {
    for (const Visit& visit : normalVisits) {
        if (visit.day != row.day || visit.key != row.key) { continue; }
        if (spansSlot(visit, row, reserved_end)) { return true; }
    }
    return false;
}

bool noticeSatisfied(const Plan& plan, const Candidate& row) {
    if (row.day != plan.request.now_day) { return true; }
    return row.start >= plan.request.now_minute + 60;
}

bool slotIsFree(const Plan& plan, const Entry& doctor, const Candidate& row) {
    const Minutes reserved_end = reservedEnd(row, plan.rules);
    if (!noticeSatisfied(plan, row)) { return false; }
    if (!openingAdmits(doctor, row, reserved_end)) { return false; }
    return !bookingConflict(plan.normal.bookings, row, reserved_end);
}

bool doctorAllowed(const Plan& plan, const std::string& key) {
    if (plan.request.urgent || plan.normal.preferred.empty()) { return true; }
    return key == plan.normal.preferred;
}

Minutes doctorLoad(const Plan& plan, const Entry& doctor) {
    Minutes count = 0;
    for (const Visit& visit : plan.normal.bookings) {
        if (visit.day == plan.day && visit.key == doctor.key) { count += 1; }
    }
    return count;
}

bool underDailyCap(const Plan& plan, const Entry& doctor) {
    if (!doctorAllowed(plan, doctor.key)) { return false; }
    return doctorLoad(plan, doctor) < 4;
}

bool onHoliday(const std::vector<Minutes>& holidays, Minutes day) {
    return std::find(holidays.begin(), holidays.end(), day) != holidays.end();
}

Minutes horizonLast(const Request& request) {
    return std::min({request.requested_day + request.horizon_days,
                     request.requested_day + 14, kMaxDay});
}

std::vector<Minutes> candidateDays(const Request& request) {
    const Minutes last = horizonLast(request);
    std::vector<Minutes> days;
    for (Minutes day = request.requested_day; day <= last; day += 1) {
        if (!onHoliday(request.holidays, day)) { days.push_back(day); }
    }
    return days;
}

Candidate candidateAt(const Plan& plan, const Entry& doctor, Minutes start) {
    return Candidate{plan.day, start, start + plan.rules.duration, doctor.key, doctor.name};
}

void scanStartTimes(std::vector<Candidate>& out, const Plan& plan, const Entry& doctor) {
    for (Minutes start = 0; start <= 1435; start += 5) {
        const Candidate row = candidateAt(plan, doctor, start);
        if (slotIsFree(plan, doctor, row)) { out.push_back(row); }
    }
}

void dayCandidates(std::vector<Candidate>& out, const Plan& plan) {
    for (const Entry& doctor : plan.normal.doctors) {
        if (underDailyCap(plan, doctor)) { scanStartTimes(out, plan, doctor); }
    }
}

std::vector<Candidate> collectCandidates(const Request& request, const Normalised& normal,
                              const Rules& rules) {
    std::vector<Candidate> found;
    for (const Minutes day : candidateDays(request)) {
        dayCandidates(found, Plan{request, normal, rules, day});
    }
    return found;
}

std::vector<Candidate> offeredCandidates(const Request& request, const Normalised& normal,
                               const Rules& rules) {
    return collectCandidates(request, normal, rules);
}

bool ranksBefore(const Candidate& row, const Candidate& best) {
    if (row.day != best.day) { return row.day < best.day; }
    if (row.start != best.start) { return row.start < best.start; }
    return row.key < best.key;
}

const Candidate* earliestCandidate(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) { return nullptr; }
    const Candidate* best = &candidates.front();
    for (const Candidate& row : candidates) {
        if (ranksBefore(row, *best)) { best = &row; }
    }
    return best;
}

Slot packSlot(const Candidate& best) {
    return Slot{best.day, best.start, best.end, best.doctor, kTrace};
}

Outcome rejectedOutcome(const Failure& failure) {
    return Outcome{true, failure, Slot{}};
}

Outcome noSlotOutcome() {
    return rejectedOutcome(plainFailure("NO_SLOT"));
}

Outcome chooseEarliest(const std::vector<Candidate>& candidates) {
    const Candidate* best = earliestCandidate(candidates);
    if (best == nullptr) { return noSlotOutcome(); }
    return Outcome{false, kNoFailure, packSlot(*best)};
}

Outcome pickEarliest(const std::vector<Candidate>& candidates) {
    return chooseEarliest(candidates);
}

/** Return the earliest valid appointment or the first validation error. */
Outcome solution(const Request& request) {
    const Normalised normal = normalisedRequest(request);
    const Failure failure = validationFailure(request, normal);
    if (failurePresent(failure)) { return rejectedOutcome(failure); }
    const Rules rules = rulesFor(normal.kind);
    return pickEarliest(offeredCandidates(request, normal, rules));
}
