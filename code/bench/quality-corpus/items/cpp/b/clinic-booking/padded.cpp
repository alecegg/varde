#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <set>
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

using Visits = std::vector<const Visit*>;

struct Rules {
    Minutes duration;
    Minutes buffer;
};

struct KindRule {
    const char* kind;
    Minutes duration;
    Minutes buffer;
};

struct Opening {
    Minutes open;
    Minutes close;
    bool closed;
};

struct Candidate {
    Minutes day;
    Minutes start;
    Minutes end;
    std::string key;
    std::string doctor;
};

constexpr Minutes kMaxDay = 1000000;
constexpr Minutes kLastStart = 1435;
constexpr Minutes kGrid = 5;
constexpr Minutes kDailyCap = 4;
constexpr Minutes kNotice = 60;
constexpr Minutes kLunchStart = 720;
constexpr Minutes kLunchEnd = 780;
constexpr Index kMaxDoctors = 12;
constexpr Index kKindCount = 3;

constexpr const char* kNameLetters =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -";

const Failure kNoFailure{"", false, 0};
const Failure kBadRequest{"BAD_REQUEST", false, 0};
const Failure kBadDoctors{"BAD_DOCTORS", false, 0};
const Failure kBadHoliday{"BAD_HOLIDAY", false, 0};
const Failure kBadBooking{"BAD_BOOKING", false, 0};
const Failure kUnknownDoctor{"UNKNOWN_DOCTOR", false, 0};
const Failure kBadDayOrder{"BAD_DAY_ORDER", false, 0};
const Failure kNoSlot{"NO_SLOT", false, 0};

const KindRule kKindRules[kKindCount] = {
    {"checkup", 20, 5}, {"consultation", 30, 10}, {"procedure", 60, 15}};

const Opening kOpenings[7] = {{540, 1020, false}, {540, 1020, false}, {540, 1020, false},
                              {540, 1020, false}, {540, 1020, false}, {600, 840, false},
                              {0, 0, true}};

const char* const kTraceNames[10] = {
    "normalised",      "validated",           "holiday-filter",   "hours-and-lunch",
    "notice",          "doctor-availability", "daily-cap",        "booking-conflicts",
    "urgent-priority", "earliest-grid-slot"};

std::string trimSpaces(const std::string& text) {
    const Index first = text.find_first_not_of(' ');
    if (first == std::string::npos) return "";
    const Index last = text.find_last_not_of(' ');
    return text.substr(first, last - first + 1);
}

std::string lowerAscii(std::string text) {
    for (char& letter : text) {
        const bool upper = letter >= 'A' && letter <= 'Z';
        if (upper) letter = static_cast<char>(letter - 'A' + 'a');
    }
    return text;
}

Entry normalisedDoctor(const Doctor& doctor) {
    const std::string name = trimSpaces(doctor.name);
    return Entry{name, lowerAscii(name), doctor.windows};
}

Normalised normaliseRequest(const Request& request) {
    Normalised normal;
    normal.kind = lowerAscii(trimSpaces(request.kind));
    normal.preferred = lowerAscii(trimSpaces(request.preferred_doctor));
    for (const Doctor& doctor : request.doctors) {
        normal.doctors.push_back(normalisedDoctor(doctor));
    }
    for (const Booking& booking : request.bookings) {
        const std::string key = lowerAscii(trimSpaces(booking.doctor));
        normal.bookings.push_back(Visit{booking.day, booking.start, booking.end, key});
    }
    return normal;
}

bool namesDoctor(const Normalised& normal, const std::string& key) {
    for (const Entry& doctor : normal.doctors) {
        if (doctor.key == key) return true;
    }
    return false;
}

Rules rulesFor(const std::string& kind) {
    Rules found{0, 0};
    for (const KindRule& row : kKindRules) {
        if (kind == row.kind) found = Rules{row.duration, row.buffer};
    }
    return found;
}

bool freshDoctor(const Entry& doctor, std::set<std::string>& keys) {
    const bool shaped = !doctor.name.empty() &&
                        doctor.name.find_first_not_of(kNameLetters) == std::string::npos;
    return shaped && keys.insert(doctor.key).second;
}

Failure scalarFailure(const Request& request, const Normalised& normal) {
    const bool days_fit = request.now_day >= 0 && request.now_day <= kMaxDay &&
                          request.requested_day >= 0 && request.requested_day <= kMaxDay;
    const bool time_fits = request.now_minute >= 0 && request.now_minute <= 1439 &&
                           request.horizon_days >= 0 && request.horizon_days <= 14;
    if (!days_fit || !time_fits || rulesFor(normal.kind).duration == 0) return kBadRequest;
    return kNoFailure;
}

Failure doctorFailure(const Normalised& normal) {
    const auto& doctors = normal.doctors;
    if (doctors.empty() || doctors.size() > kMaxDoctors) return kBadDoctors;
    std::set<std::string> keys;
    Index position = 0;
    for (const Entry& doctor : doctors) {
        if (!freshDoctor(doctor, keys)) {
            return Failure{"BAD_DOCTORS", true, static_cast<Minutes>(position)};
        }
        position += 1;
    }
    return kNoFailure;
}

Failure windowFailure(const Normalised& normal) {
    Index position = 0;
    for (const Entry& doctor : normal.doctors) {
        bool stray = doctor.windows.size() > 8;
        for (const Window& window : doctor.windows) {
            stray = stray || window.weekday < 0 || window.weekday > 6 || window.open < 0 ||
                    window.open >= window.close || window.close > 1440;
        }
        if (stray) return Failure{"BAD_WINDOW", true, static_cast<Minutes>(position)};
        position += 1;
    }
    return kNoFailure;
}

Failure holidayFailure(const Request& request) {
    const auto& holidays = request.holidays;
    if (holidays.size() > 60) return kBadHoliday;
    std::set<Minutes> seen;
    Index position = 0;
    for (const Minutes day : holidays) {
        const bool spaced = day >= 0 && day <= kMaxDay && seen.insert(day).second;
        if (!spaced) return Failure{"BAD_HOLIDAY", true, static_cast<Minutes>(position)};
        position += 1;
    }
    return kNoFailure;
}

Failure bookingFailure(const Normalised& normal) {
    const auto& visits = normal.bookings;
    if (visits.size() > 200) return kBadBooking;
    Index position = 0;
    for (const Visit& visit : visits) {
        if (visit.day < 0 || visit.day > kMaxDay || visit.start < 0 ||
            visit.start >= visit.end || visit.end > 1440 ||
            !namesDoctor(normal, visit.key)) {
            return Failure{"BAD_BOOKING", true, static_cast<Minutes>(position)};
        }
        position += 1;
    }
    return kNoFailure;
}

Failure preferenceFailure(const Request& request, const Normalised& normal) {
    if (!normal.preferred.empty() && !namesDoctor(normal, normal.preferred)) {
        return kUnknownDoctor;
    }
    const bool ordered = request.requested_day >= request.now_day &&
                         request.requested_day - request.now_day <= 8;
    if (!ordered) return kBadDayOrder;
    return kNoFailure;
}

Failure firstFailure(const Request& request, const Normalised& normal) {
    Failure failure = scalarFailure(request, normal);
    if (failure.code.empty()) failure = doctorFailure(normal);
    if (failure.code.empty()) failure = windowFailure(normal);
    if (failure.code.empty()) failure = holidayFailure(request);
    if (failure.code.empty()) failure = bookingFailure(normal);
    if (failure.code.empty()) failure = preferenceFailure(request, normal);
    return failure;
}

std::vector<Minutes> candidateDays(const Request& request) {
    const Minutes first = request.requested_day;
    const Minutes last = std::min({first + request.horizon_days, first + 14, kMaxDay});
    std::vector<Minutes> days;
    for (Minutes day = first; day <= last; day += 1) {
        if (std::find(request.holidays.begin(), request.holidays.end(), day) ==
            request.holidays.end()) {
            days.push_back(day);
        }
    }
    return days;
}

bool openingAdmits(const Entry& doctor, Minutes weekday, Minutes start, Minutes reserved) {
    const Opening hours = kOpenings[weekday];
    const bool inside = !hours.closed && start >= hours.open && reserved <= hours.close;
    const bool clear = !(start < kLunchEnd && reserved > kLunchStart);
    if (!inside || !clear) return false;
    for (const Window& window : doctor.windows) {
        if (window.weekday == weekday && window.open <= start && reserved <= window.close) {
            return true;
        }
    }
    return false;
}

Visits dayVisits(const Normalised& normal, Minutes day, const std::string& key) {
    Visits found;
    for (const Visit& visit : normal.bookings) {
        if (visit.day == day && visit.key == key) found.push_back(&visit);
    }
    return found;
}

bool slotFits(const Request& request, const Entry& doctor, const Candidate& row, Minutes reserved,
              const Visits& visits) {
    if ((row.day == request.now_day && row.start < request.now_minute + kNotice) ||
        !openingAdmits(doctor, row.day % 7, row.start, reserved)) {
        return false;
    }
    for (const Visit* visit : visits) {
        if (row.start < visit->end && visit->start < reserved) return false;
    }
    return true;
}

void addCandidates(const Request& request, const Entry& doctor, Minutes day, const Rules& rules,
                   const Visits& visits, std::vector<Candidate>& into) {
    if (visits.size() >= kDailyCap) return;
    for (Minutes start = 0; start <= kLastStart; start += kGrid) {
        const Candidate row{day, start, start + rules.duration, doctor.key, doctor.name};
        const Minutes reserved = row.end + rules.buffer;
        if (slotFits(request, doctor, row, reserved, visits)) into.push_back(row);
    }
}

std::vector<Candidate> collectCandidates(const Request& request, const Normalised& normal,
                                         const Rules& rules) {
    std::vector<Candidate> candidates;
    for (const Minutes day : candidateDays(request)) {
        for (const Entry& doctor : normal.doctors) {
            if (!request.urgent && !normal.preferred.empty() &&
                doctor.key != normal.preferred) continue;
            const Visits visits = dayVisits(normal, day, doctor.key);
            addCandidates(request, doctor, day, rules, visits, candidates);
        }
    }
    return candidates;
}

Outcome assembleOutcome(const Candidate& chosen) {
    Slot slot;
    slot.day = chosen.day;
    slot.start = chosen.start;
    slot.end = chosen.end;
    slot.doctor = chosen.doctor;
    slot.trace.insert(slot.trace.end(), kTraceNames, kTraceNames + 10);
    return Outcome{false, kNoFailure, slot};
}

/** Return the earliest valid appointment or the first validation error. */
Outcome solution(const Request& request) {
    const Normalised normal = normaliseRequest(request);
    const Failure failure = firstFailure(request, normal);
    if (!failure.code.empty()) return Outcome{true, failure, Slot{}};
    const Rules rules = rulesFor(normal.kind);
    const std::vector<Candidate> candidates = collectCandidates(request, normal, rules);
    if (candidates.empty()) return Outcome{true, kNoSlot, Slot{}};
    const Candidate* chosen = &candidates.front();
    for (const Candidate& row : candidates) {
        const bool sooner_day = row.day < chosen->day;
        const bool sooner_slot = row.day == chosen->day && (row.start < chosen->start ||
                                 (row.start == chosen->start && row.key < chosen->key));
        if (sooner_day || sooner_slot) chosen = &row;
    }
    return assembleOutcome(*chosen);
}
