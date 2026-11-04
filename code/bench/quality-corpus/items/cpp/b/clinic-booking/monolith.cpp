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
    std::size_t kind_first = 0;
    while (kind_first < request.kind.size() && request.kind[kind_first] == ' ') {
        kind_first += 1;
    }
    std::size_t kind_last = request.kind.size();
    while (kind_last > kind_first && request.kind[kind_last - 1] == ' ') {
        kind_last -= 1;
    }
    std::string kind_text = request.kind.substr(kind_first, kind_last - kind_first);
    for (char& letter : kind_text) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    std::size_t wanted_first = 0;
    while (wanted_first < request.preferred_doctor.size() &&
           request.preferred_doctor[wanted_first] == ' ') {
        wanted_first += 1;
    }
    std::size_t wanted_last = request.preferred_doctor.size();
    while (wanted_last > wanted_first && request.preferred_doctor[wanted_last - 1] == ' ') {
        wanted_last -= 1;
    }
    std::string wanted_text =
        request.preferred_doctor.substr(wanted_first, wanted_last - wanted_first);
    for (char& letter : wanted_text) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }

    std::vector<Entry> doctors;
    for (const Doctor& given : request.doctors) {
        std::size_t name_first = 0;
        while (name_first < given.name.size() && given.name[name_first] == ' ') {
            name_first += 1;
        }
        std::size_t name_last = given.name.size();
        while (name_last > name_first && given.name[name_last - 1] == ' ') {
            name_last -= 1;
        }
        std::string name_text = given.name.substr(name_first, name_last - name_first);
        std::string key_text = name_text;
        for (char& letter : key_text) {
            if (letter >= 'A' && letter <= 'Z') {
                letter = static_cast<char>(letter - 'A' + 'a');
            }
        }
        doctors.push_back(Entry{name_text, key_text, given.windows});
    }

    std::vector<Visit> visits;
    for (const Booking& given : request.bookings) {
        std::size_t key_first = 0;
        while (key_first < given.doctor.size() && given.doctor[key_first] == ' ') {
            key_first += 1;
        }
        std::size_t key_last = given.doctor.size();
        while (key_last > key_first && given.doctor[key_last - 1] == ' ') {
            key_last -= 1;
        }
        std::string visit_key = given.doctor.substr(key_first, key_last - key_first);
        for (char& letter : visit_key) {
            if (letter >= 'A' && letter <= 'Z') {
                letter = static_cast<char>(letter - 'A' + 'a');
            }
        }
        visits.push_back(Visit{given.day, given.start, given.end, visit_key});
    }

    const bool days_fit = request.now_day >= 0 && request.now_day <= kMaxDay &&
                          request.requested_day >= 0 && request.requested_day <= kMaxDay;
    const bool time_fits = request.now_minute >= 0 && request.now_minute <= 1439 &&
                           request.horizon_days >= 0 && request.horizon_days <= 14;
    const bool kind_known = kind_text == "checkup" || kind_text == "consultation" ||
                            kind_text == "procedure";
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
            if (doctors[earlier].key == doctor.key) {
                repeated = true;
            }
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
            if (!weekday_ok || !clock_ok) {
                bad = true;
            }
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
        bool repeated = false;
        for (Index earlier = 0; earlier < position; earlier += 1) {
            if (request.holidays[earlier] == holiday) {
                repeated = true;
            }
        }
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
        bool known = false;
        for (const Entry& doctor : doctors) {
            if (doctor.key == visit.key) {
                known = true;
            }
        }
        if (!clock_ok || !known) {
            return Outcome{true, Failure{"BAD_BOOKING", true, static_cast<Minutes>(position)},
                           Slot{}};
        }
    }

    if (!wanted_text.empty()) {
        bool known = false;
        for (const Entry& doctor : doctors) {
            if (doctor.key == wanted_text) {
                known = true;
            }
        }
        if (!known) {
            return Outcome{true, Failure{"UNKNOWN_DOCTOR", false, 0}, Slot{}};
        }
    }

    const bool ordered = request.requested_day >= request.now_day &&
                         request.requested_day - request.now_day <= 8;
    if (!ordered) {
        return Outcome{true, Failure{"BAD_DAY_ORDER", false, 0}, Slot{}};
    }

    Rules rules{20, 5};
    if (kind_text == "consultation") {
        rules = Rules{30, 10};
    }
    if (kind_text == "procedure") {
        rules = Rules{60, 15};
    }

    std::vector<Candidate> candidates;
    const Minutes last_day =
        std::min({request.requested_day + request.horizon_days, request.requested_day + 14,
                  kMaxDay});
    std::vector<Minutes> open_days;
    for (Minutes day = request.requested_day; day <= last_day; day += 1) {
        bool closed = false;
        for (const Minutes holiday : request.holidays) {
            if (holiday == day) {
                closed = true;
            }
        }
        if (!closed) {
            open_days.push_back(day);
        }
    }
    for (const Minutes day : open_days) {
        for (const Entry& doctor : doctors) {
            const bool wants_doctor = !wanted_text.empty();
            if (!request.urgent && wants_doctor && doctor.key != wanted_text) {
                continue;
            }
            Minutes booked = 0;
            for (Index seat = 0; seat < visits.size(); seat += 1) {
                const Visit& taken = visits[seat];
                if (taken.day == day && taken.key == doctor.key) {
                    booked += 1;
                }
            }
            if (booked >= 4) {
                continue;
            }
            const Minutes weekday = day % 7;
            const Minutes opening = weekday == 5 ? 600 : 540;
            const Minutes closing = weekday == 5 ? 840 : 1020;
            for (Minutes start = 0; start <= 1435; start += 5) {
                const Minutes end = start + rules.duration;
                const Minutes reserved_end = end + rules.buffer;
                if (day == request.now_day && start < request.now_minute + 60) {
                    continue;
                }
                const bool inside_hours =
                    weekday != 6 && start >= opening && reserved_end <= closing;
                const bool clears_lunch = !(start < 780 && reserved_end > 720);
                if (!inside_hours || !clears_lunch) {
                    continue;
                }
                bool window_ok = false;
                for (Index option = 0; option < doctor.windows.size(); option += 1) {
                    const Window& window = doctor.windows[option];
                    const bool same_weekday = window.weekday == weekday;
                    const bool covers = window.open <= start && reserved_end <= window.close;
                    if (same_weekday && covers) {
                        window_ok = true;
                    }
                }
                if (!window_ok) {
                    continue;
                }
                bool conflict = false;
                for (Index other = 0; other < visits.size(); other += 1) {
                    const Visit& taken_slot = visits[other];
                    if (taken_slot.day != day || taken_slot.key != doctor.key) {
                        continue;
                    }
                    const bool starts_before_end = start < taken_slot.end;
                    const bool ends_after_start = taken_slot.start < reserved_end;
                    if (starts_before_end && ends_after_start) {
                        conflict = true;
                    }
                }
                if (conflict) {
                    continue;
                }
                candidates.push_back(Candidate{day, start, end, doctor.key, doctor.name});
            }
        }
    }

    if (candidates.empty()) {
        return Outcome{true, Failure{"NO_SLOT", false, 0}, Slot{}};
    }
    Index best = 0;
    for (Index row = 1; row < candidates.size(); row += 1) {
        const Candidate& candidate = candidates[row];
        const Candidate& chosen = candidates[best];
        const bool earlier_day = candidate.day < chosen.day;
        const bool same_day = candidate.day == chosen.day;
        const bool earlier_start = candidate.start < chosen.start;
        const bool same_start = candidate.start == chosen.start;
        const bool earlier_key = candidate.key < chosen.key;
        const bool same_day_earlier = same_day && (earlier_start || (same_start && earlier_key));
        if (earlier_day || same_day_earlier) {
            best = row;
        }
    }
    const Candidate picked = candidates[best];
    return Outcome{false, kNoFailure,
                   Slot{picked.day, picked.start, picked.end, picked.doctor, kTrace}};
}
