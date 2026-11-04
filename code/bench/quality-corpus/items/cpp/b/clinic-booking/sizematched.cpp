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

constexpr Minutes kMaxDay = 1000000;

constexpr Index kMaxDoctors = 12;

constexpr const char* kNameLetters =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -";

const Failure kNoFailure{"", false, 0};

const std::vector<std::string> kTrace = {
    "normalised",      "validated",           "holiday-filter",   "hours-and-lunch",
    "notice",          "doctor-availability", "daily-cap",        "booking-conflicts",
    "urgent-priority", "earliest-grid-slot"};

/** Return the earliest valid appointment or the first validation error. */
Outcome solution(const Request& request) {
    const std::string blanks = " ";

    const std::size_t kind_first = request.kind.find_first_not_of(blanks);
    const bool has_kind = kind_first != std::string::npos;
    const std::size_t kind_last =
        has_kind ? request.kind.find_last_not_of(blanks) + 1 : std::string::npos;
    std::string kind = has_kind ? request.kind.substr(kind_first, kind_last - kind_first) : "";
    for (char& letter : kind) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    const std::size_t wanted_first = request.preferred_doctor.find_first_not_of(blanks);
    const bool has_wanted = wanted_first != std::string::npos;
    const std::size_t wanted_last =
        has_wanted ? request.preferred_doctor.find_last_not_of(blanks) + 1 : std::string::npos;
    std::string wanted =
        has_wanted
            ? request.preferred_doctor.substr(wanted_first, wanted_last - wanted_first)
            : "";
    for (char& letter : wanted) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    std::vector<Entry> doctors;
    doctors.reserve(request.doctors.size());
    for (const Doctor& given : request.doctors) {
        const std::size_t first = given.name.find_first_not_of(blanks);
        const bool named = first != std::string::npos;
        const std::size_t last =
            named ? given.name.find_last_not_of(blanks) + 1 : std::string::npos;
        std::string name = named ? given.name.substr(first, last - first) : "";
        std::string key = name;
        for (char& letter : key) {
            if (letter >= 'A' && letter <= 'Z') {
                letter = static_cast<char>(letter - 'A' + 'a');
            }
        }
        doctors.push_back(Entry{name, key, given.windows});
    }

    std::vector<Visit> visits;
    visits.reserve(request.bookings.size());
    for (const Booking& given : request.bookings) {
        const std::size_t first = given.doctor.find_first_not_of(blanks);
        const bool named = first != std::string::npos;
        const std::size_t last =
            named ? given.doctor.find_last_not_of(blanks) + 1 : std::string::npos;
        std::string key = named ? given.doctor.substr(first, last - first) : "";
        for (char& letter : key) {
            if (letter >= 'A' && letter <= 'Z') {
                letter = static_cast<char>(letter - 'A' + 'a');
            }
        }
        visits.push_back(Visit{given.day, given.start, given.end, key});
    }

    const bool days_fit = request.now_day >= 0 && request.now_day <= kMaxDay &&
                          request.requested_day >= 0 && request.requested_day <= kMaxDay;
    const bool time_fits = request.now_minute >= 0 && request.now_minute <= 1439 &&
                           request.horizon_days >= 0 && request.horizon_days <= 14;
    const bool kind_known =
        kind == "checkup" || kind == "consultation" || kind == "procedure";
    if (!days_fit || !time_fits || !kind_known) {
        return Outcome{true, Failure{"BAD_REQUEST", false, 0}, Slot{}};
    }

    if (doctors.empty() || doctors.size() > kMaxDoctors) {
        return Outcome{true, Failure{"BAD_DOCTORS", false, 0}, Slot{}};
    }
    for (Index position = 0; position < doctors.size(); position += 1) {
        const Entry& doctor = doctors[position];
        bool repeated = false;
        for (Index earlier = 0; earlier < position; earlier += 1) {
            repeated = repeated || doctors[earlier].key == doctor.key;
        }
        const bool shaped = !doctor.name.empty() &&
                            doctor.name.find_first_not_of(kNameLetters) == std::string::npos;
        if (!shaped || repeated) {
            return Outcome{true, Failure{"BAD_DOCTORS", true, static_cast<Minutes>(position)},
                           Slot{}};
        }
    }

    for (Index position = 0; position < doctors.size(); position += 1) {
        const Entry& doctor = doctors[position];
        bool bad = doctor.windows.size() > 8;
        for (const Window& window : doctor.windows) {
            const bool weekday_ok = window.weekday >= 0 && window.weekday <= 6;
            const bool clock_ok =
                window.open >= 0 && window.open < window.close && window.close <= 1440;
            bad = bad || !weekday_ok || !clock_ok;
        }
        if (bad) {
            return Outcome{true, Failure{"BAD_WINDOW", true, static_cast<Minutes>(position)},
                           Slot{}};
        }
    }

    if (request.holidays.size() > 60) {
        return Outcome{true, Failure{"BAD_HOLIDAY", false, 0}, Slot{}};
    }
    for (Index position = 0; position < request.holidays.size(); position += 1) {
        const Minutes holiday = request.holidays[position];
        const bool repeated =
            std::find(request.holidays.begin(), request.holidays.begin() + position, holiday) !=
            request.holidays.begin() + position;
        const bool day_ok = holiday >= 0 && holiday <= kMaxDay;
        if (!day_ok || repeated) {
            return Outcome{true, Failure{"BAD_HOLIDAY", true, static_cast<Minutes>(position)},
                           Slot{}};
        }
    }

    if (visits.size() > 200) {
        return Outcome{true, Failure{"BAD_BOOKING", false, 0}, Slot{}};
    }
    for (Index position = 0; position < visits.size(); position += 1) {
        const Visit& visit = visits[position];
        const bool clock_ok = visit.day >= 0 && visit.day <= kMaxDay && visit.start >= 0 &&
                              visit.start < visit.end && visit.end <= 1440;
        bool knows_doctor = false;
        for (const Entry& doctor : doctors) {
            knows_doctor = knows_doctor || doctor.key == visit.key;
        }
        if (!clock_ok || !knows_doctor) {
            return Outcome{true, Failure{"BAD_BOOKING", true, static_cast<Minutes>(position)},
                           Slot{}};
        }
    }

    bool wanted_known = wanted.empty();
    for (const Entry& doctor : doctors) {
        wanted_known = wanted_known || doctor.key == wanted;
    }
    if (!wanted_known) {
        return Outcome{true, Failure{"UNKNOWN_DOCTOR", false, 0}, Slot{}};
    }

    const bool ordered = request.requested_day >= request.now_day &&
                         request.requested_day - request.now_day <= 8;
    if (!ordered) {
        return Outcome{true, Failure{"BAD_DAY_ORDER", false, 0}, Slot{}};
    }

    const Rules rules = kind == "consultation" ? Rules{30, 10}
                        : kind == "procedure" ? Rules{60, 15} : Rules{20, 5};

    const Minutes first_day = request.requested_day;
    const Minutes last_day =
        std::min({first_day + request.horizon_days, first_day + 14, kMaxDay});
    std::vector<Minutes> days;
    for (Minutes day = first_day; day <= last_day; day += 1) {
        const bool closed =
            std::find(request.holidays.begin(), request.holidays.end(), day) !=
            request.holidays.end();
        if (!closed) {
            days.push_back(day);
        }
    }

    Candidate best{};
    bool found = false;
    for (const Minutes day : days) {
        for (const Entry& doctor : doctors) {
            const bool eligible = request.urgent || wanted.empty() || doctor.key == wanted;
            if (!eligible) {
                continue;
            }
            Minutes booked = 0;
            for (const Visit& visit : visits) {
                if (visit.day == day && visit.key == doctor.key) {
                    booked += 1;
                }
            }
            if (booked >= 4) {
                continue;
            }
            const Minutes weekday = day % 7;
            const Minutes open = weekday == 5 ? 600 : 540;
            const Minutes close = weekday == 5 ? 840 : 1020;
            for (Minutes start = 0; start <= 1435; start += 5) {
                const Minutes end = start + rules.duration;
                const Minutes reserved_end = end + rules.buffer;
                const bool too_soon = day == request.now_day && start < request.now_minute + 60;
                const bool inside_hours =
                    weekday != 6 && start >= open && reserved_end <= close;
                const bool clears_lunch = !(start < 780 && reserved_end > 720);
                bool window_fits = false;
                for (const Window& window : doctor.windows) {
                    window_fits = window_fits || (window.weekday == weekday &&
                                                  window.open <= start &&
                                                  reserved_end <= window.close);
                }
                bool conflict = false;
                for (const Visit& visit : visits) {
                    conflict = conflict || (visit.day == day && visit.key == doctor.key &&
                                            start < visit.end && visit.start < reserved_end);
                }
                if (too_soon) {
                    continue;
                }
                if (!inside_hours) {
                    continue;
                }
                if (!clears_lunch) {
                    continue;
                }
                if (!window_fits) {
                    continue;
                }
                if (conflict) {
                    continue;
                }
                const bool same_day = day == best.day;
                const bool earlier_start = start < best.start;
                const bool same_start = start == best.start;
                const bool earlier_key = doctor.key < best.key;
                const bool earlier =
                    !found || day < best.day ||
                    (same_day && (earlier_start || (same_start && earlier_key)));
                if (earlier) {
                    best = Candidate{day, start, end, doctor.key, doctor.name};
                    found = true;
                }
            }
        }
    }

    if (!found) {
        return Outcome{true, Failure{"NO_SLOT", false, 0}, Slot{}};
    }
    const Slot slot{best.day, best.start, best.end, best.doctor, kTrace};
    return Outcome{false, kNoFailure, slot};
}
