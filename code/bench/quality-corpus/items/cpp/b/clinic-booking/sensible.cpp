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

std::string trimSpaces(const std::string& text) {
    Index first = 0;
    while (first < text.size() && text[first] == ' ') {
        first += 1;
    }
    Index last = text.size();
    while (last > first && text[last - 1] == ' ') {
        last -= 1;
    }
    return text.substr(first, last - first);
}

std::string lowerAscii(const std::string& text) {
    std::string lowered = text;
    for (char& letter : lowered) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return lowered;
}

Rules rulesFor(const std::string& kind) {
    if (kind == "consultation") {
        return Rules{30, 10};
    }
    if (kind == "procedure") {
        return Rules{60, 15};
    }
    return Rules{20, 5};
}

Normalised normalise(const Request& request) {
    Normalised normal;
    normal.kind = lowerAscii(trimSpaces(request.kind));
    normal.preferred = lowerAscii(trimSpaces(request.preferred_doctor));
    for (const Doctor& doctor : request.doctors) {
        const std::string name = trimSpaces(doctor.name);
        normal.doctors.push_back(Entry{name, lowerAscii(name), doctor.windows});
    }
    for (const Booking& booking : request.bookings) {
        const std::string key = lowerAscii(trimSpaces(booking.doctor));
        normal.bookings.push_back(Visit{booking.day, booking.start, booking.end, key});
    }
    return normal;
}

void checkScalars(const Request& request, const Normalised& normal) {
    const bool days_fit = request.now_day >= 0 && request.now_day <= kMaxDay &&
                          request.requested_day >= 0 && request.requested_day <= kMaxDay;
    const bool time_fits = request.now_minute >= 0 && request.now_minute <= 1439 &&
                           request.horizon_days >= 0 && request.horizon_days <= 14;
    const bool kind_known = normal.kind == "checkup" || normal.kind == "consultation" ||
                            normal.kind == "procedure";
    if (!days_fit || !time_fits || !kind_known) {
        throw Rejection{Failure{"BAD_REQUEST", false, 0}};
    }
}

bool nameShaped(const std::string& name) {
    if (name.empty()) {
        return false;
    }
    return name.find_first_not_of(kNameLetters) == std::string::npos;
}

void checkDoctors(const Normalised& normal) {
    if (normal.doctors.empty() || normal.doctors.size() > kMaxDoctors) {
        throw Rejection{Failure{"BAD_DOCTORS", false, 0}};
    }
    for (Index position = 0; position < normal.doctors.size(); ++position) {
        const Entry& doctor = normal.doctors[position];
        bool repeated = false;
        for (Index earlier = 0; earlier < position; ++earlier) {
            repeated = repeated || normal.doctors[earlier].key == doctor.key;
        }
        if (!nameShaped(doctor.name) || repeated) {
            throw Rejection{Failure{"BAD_DOCTORS", true, static_cast<Minutes>(position)}};
        }
    }
}

void checkWindows(const Normalised& normal) {
    for (Index position = 0; position < normal.doctors.size(); position += 1) {
        const Entry& doctor = normal.doctors[position];
        bool bad = doctor.windows.size() > 8;
        for (const Window& window : doctor.windows) {
            const bool stray = window.weekday < 0 || window.weekday > 6 ||
                               window.open < 0 || window.open >= window.close ||
                               window.close > 1440;
            bad = bad || stray;
        }
        if (bad) {
            throw Rejection{Failure{"BAD_WINDOW", true, static_cast<Minutes>(position)}};
        }
    }
}

void checkHolidays(const Request& request) {
    if (request.holidays.size() > 60) {
        throw Rejection{Failure{"BAD_HOLIDAY", false, 0}};
    }
    for (Index position = 0; position < request.holidays.size(); position += 1) {
        const Minutes day = request.holidays[position];
        const bool repeated =
            std::find(request.holidays.begin(), request.holidays.begin() + position, day) !=
            request.holidays.begin() + position;
        if (day < 0 || day > kMaxDay || repeated) {
            throw Rejection{Failure{"BAD_HOLIDAY", true, static_cast<Minutes>(position)}};
        }
    }
}

bool namesDoctor(const Normalised& normal, const std::string& key) {
    for (const Entry& doctor : normal.doctors) {
        if (doctor.key == key) {
            return true;
        }
    }
    return false;
}

void checkBookings(const Normalised& normal) {
    if (normal.bookings.size() > 200) {
        throw Rejection{Failure{"BAD_BOOKING", false, 0}};
    }
    for (Index position = 0; position < normal.bookings.size(); position += 1) {
        const Visit& visit = normal.bookings[position];
        const bool bad = visit.day < 0 || visit.day > kMaxDay || visit.start < 0 ||
                         visit.start >= visit.end || visit.end > 1440;
        if (bad || !namesDoctor(normal, visit.key)) {
            throw Rejection{Failure{"BAD_BOOKING", true, static_cast<Minutes>(position)}};
        }
    }
}

void checkRequest(const Request& request, const Normalised& normal) {
    checkScalars(request, normal);
    checkDoctors(normal);
    checkWindows(normal);
    checkHolidays(request);
    checkBookings(normal);
    if (!normal.preferred.empty() && !namesDoctor(normal, normal.preferred)) {
        throw Rejection{Failure{"UNKNOWN_DOCTOR", false, 0}};
    }
    const bool ordered = request.requested_day >= request.now_day &&
                         request.requested_day - request.now_day <= 8;
    if (!ordered) {
        throw Rejection{Failure{"BAD_DAY_ORDER", false, 0}};
    }
}

bool openingAdmits(const Entry& doctor, Minutes weekday, const Candidate& candidate,
                   Minutes reserved_end) {
    const Minutes open = weekday == 5 ? 600 : 540;
    const Minutes close = weekday == 5 ? 840 : 1020;
    const bool inside_hours = weekday != 6 && candidate.start >= open &&
                              reserved_end <= close;
    const bool clears_lunch = !(candidate.start < 780 && reserved_end > 720);
    if (!inside_hours || !clears_lunch) {
        return false;
    }
    for (const Window& window : doctor.windows) {
        if (window.weekday == weekday && window.open <= candidate.start &&
            reserved_end <= window.close) {
            return true;
        }
    }
    return false;
}

bool bookingConflict(const std::vector<Visit>& bookings, const Candidate& candidate,
                     Minutes reserved_end) {
    for (const Visit& visit : bookings) {
        if (visit.day != candidate.day || visit.key != candidate.key) {
            continue;
        }
        if (candidate.start < visit.end && visit.start < reserved_end) {
            return true;
        }
    }
    return false;
}

bool slotFits(const Request& request, const Normalised& normal, const Entry& doctor,
              const Candidate& candidate, const Rules& rules) {
    const Minutes weekday = candidate.day % 7;
    const Minutes reserved_end = candidate.end + rules.buffer;
    if (candidate.day == request.now_day && candidate.start < request.now_minute + 60) {
        return false;
    }
    if (!openingAdmits(doctor, weekday, candidate, reserved_end)) {
        return false;
    }
    return !bookingConflict(normal.bookings, candidate, reserved_end);
}

bool doctorFits(const Request& request, const Normalised& normal, const Entry& doctor,
                Minutes day) {
    if (!request.urgent && !normal.preferred.empty() && doctor.key != normal.preferred) {
        return false;
    }
    Minutes booked = 0;
    for (const Visit& visit : normal.bookings) {
        if (visit.day == day && visit.key == doctor.key) {
            booked += 1;
        }
    }
    return booked < 4;
}

std::vector<Minutes> candidateDays(const Request& request) {
    const Minutes last = std::min({request.requested_day + request.horizon_days,
                                   request.requested_day + 14, kMaxDay});
    std::vector<Minutes> days;
    for (Minutes day = request.requested_day; day <= last; day += 1) {
        const bool closed =
            std::find(request.holidays.begin(), request.holidays.end(), day) !=
            request.holidays.end();
        if (!closed) {
            days.push_back(day);
        }
    }
    return days;
}

std::vector<Candidate> collectCandidates(const Request& request,
                                         const Normalised& normal, const Rules& rules) {
    std::vector<Candidate> candidates;
    for (const Minutes day : candidateDays(request)) {
        for (const Entry& doctor : normal.doctors) {
            if (!doctorFits(request, normal, doctor, day)) continue;
            for (Minutes start = 0; start <= 1435; start += 5) {
                const Candidate candidate{day, start, start + rules.duration, doctor.key,
                                          doctor.name};
                if (!slotFits(request, normal, doctor, candidate, rules)) continue;
                candidates.push_back(candidate);
            }
        }
    }
    return candidates;
}

const Candidate* earliestCandidate(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) {
        return nullptr;
    }
    const Candidate* best = &candidates.front();
    for (const Candidate& row : candidates) {
        const bool earlier_day = row.day < best->day;
        const bool same_day_earlier =
            row.day == best->day &&
            (row.start < best->start || (row.start == best->start && row.key < best->key));
        if (earlier_day || same_day_earlier) {
            best = &row;
        }
    }
    return best;
}

/** Return the earliest valid appointment or the first validation error. */
Outcome solution(const Request& request) {
    const Normalised normal = normalise(request);
    try {
        checkRequest(request, normal);
    } catch (const Rejection& rejection) {
        return Outcome{true, rejection.failure, Slot{}};
    }
    const Rules rules = rulesFor(normal.kind);
    const std::vector<Candidate> candidates = collectCandidates(request, normal, rules);
    const Candidate* earliest = earliestCandidate(candidates);
    if (earliest == nullptr) {
        return Outcome{true, Failure{"NO_SLOT", false, 0}, Slot{}};
    }
    return Outcome{false, kNoFailure,
                   Slot{earliest->day, earliest->start, earliest->end, earliest->doctor,
                        kTrace}};
}
