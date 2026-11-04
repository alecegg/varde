#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "solution.cpp"

const std::vector<std::string> kExpectedTrace = {
    "normalised",      "validated",           "holiday-filter",   "hours-and-lunch",
    "notice",          "doctor-availability", "daily-cap",        "booking-conflicts",
    "urgent-priority", "earliest-grid-slot"};

Outcome accepted(Slot slot) {
    slot.trace = kExpectedTrace;
    return Outcome{false, Failure{"", false, 0}, slot};
}

Outcome rejected(const std::string& code) {
    return Outcome{true, Failure{code, false, 0}, Slot{}};
}

Outcome rejected(const std::string& code, std::int64_t index) {
    return Outcome{true, Failure{code, true, index}, Slot{}};
}

Outcome result(std::int64_t day, std::int64_t start, std::int64_t end,
               const std::string& doctor_name = "Ada") {
    return accepted(Slot{day, start, end, doctor_name, {}});
}

std::string oracleTrim(const std::string& text) {
    std::size_t first = 0;
    while (first < text.size() && text[first] == ' ') {
        first += 1;
    }
    std::size_t last = text.size();
    while (last > first && text[last - 1] == ' ') {
        last -= 1;
    }
    return text.substr(first, last - first);
}

std::string oracleLower(const std::string& text) {
    std::string lowered = text;
    for (char& letter : lowered) {
        if (letter >= 'A' && letter <= 'Z') {
            letter = static_cast<char>(letter - 'A' + 'a');
        }
    }
    return lowered;
}

bool oracleNameShaped(const std::string& name) {
    if (name.empty()) {
        return false;
    }
    for (const char letter : name) {
        const bool is_letter = (letter >= 'A' && letter <= 'Z') ||
                               (letter >= 'a' && letter <= 'z');
        const bool is_digit = letter >= '0' && letter <= '9';
        if (!is_letter && !is_digit && letter != ' ' && letter != '-') {
            return false;
        }
    }
    return true;
}

bool oracleKind(const std::string& kind) {
    return kind == "checkup" || kind == "consultation" || kind == "procedure";
}

struct OracleDoctor {
    std::string name;
    std::string key;
    std::vector<Window> windows;
};

struct OracleVisit {
    std::int64_t day;
    std::int64_t start;
    std::int64_t end;
    std::string key;
};

struct OracleCandidate {
    std::int64_t day;
    std::int64_t start;
    std::int64_t end;
    std::string key;
    std::string doctor;
};

// Validate in table order, then inspect every day, doctor and grid start.
Outcome oracle(const Request& given) {
    const std::string kind = oracleLower(oracleTrim(given.kind));
    const std::string preferred = oracleLower(oracleTrim(given.preferred_doctor));
    const bool scalars_fit = given.now_day >= 0 && given.now_day <= 1000000 &&
                             given.requested_day >= 0 && given.requested_day <= 1000000 &&
                             given.now_minute >= 0 && given.now_minute <= 1439 &&
                             given.horizon_days >= 0 && given.horizon_days <= 14;
    if (!scalars_fit || !oracleKind(kind)) {
        return rejected("BAD_REQUEST");
    }
    std::vector<OracleDoctor> doctors;
    for (const Doctor& row : given.doctors) {
        const std::string name = oracleTrim(row.name);
        doctors.push_back(OracleDoctor{name, oracleLower(name), row.windows});
    }
    if (doctors.empty() || doctors.size() > 12) {
        return rejected("BAD_DOCTORS");
    }
    std::set<std::string> keys;
    for (std::size_t position = 0; position < doctors.size(); position += 1) {
        const std::int64_t index = static_cast<std::int64_t>(position);
        if (!oracleNameShaped(doctors[position].name)) {
            return rejected("BAD_DOCTORS", index);
        }
        if (!keys.insert(doctors[position].key).second) {
            return rejected("BAD_DOCTORS", index);
        }
    }
    for (std::size_t position = 0; position < doctors.size(); position += 1) {
        const std::int64_t index = static_cast<std::int64_t>(position);
        if (doctors[position].windows.size() > 8) {
            return rejected("BAD_WINDOW", index);
        }
        for (const Window& window : doctors[position].windows) {
            const bool week_fits = window.weekday >= 0 && window.weekday <= 6;
            const bool span_fits = window.open >= 0 && window.open < window.close &&
                                   window.close <= 1440;
            if (!week_fits || !span_fits) {
                return rejected("BAD_WINDOW", index);
            }
        }
    }
    if (given.holidays.size() > 60) {
        return rejected("BAD_HOLIDAY");
    }
    std::set<std::int64_t> holidays;
    for (std::size_t position = 0; position < given.holidays.size(); position += 1) {
        const std::int64_t day = given.holidays[position];
        const bool day_fits = day >= 0 && day <= 1000000;
        if (!day_fits || !holidays.insert(day).second) {
            return rejected("BAD_HOLIDAY", static_cast<std::int64_t>(position));
        }
    }
    if (given.bookings.size() > 200) {
        return rejected("BAD_BOOKING");
    }
    std::vector<OracleVisit> visits;
    for (std::size_t position = 0; position < given.bookings.size(); position += 1) {
        const Booking& row = given.bookings[position];
        const std::int64_t index = static_cast<std::int64_t>(position);
        if (row.day < 0 || row.day > 1000000) {
            return rejected("BAD_BOOKING", index);
        }
        if (row.start < 0 || row.start >= row.end || row.end > 1440) {
            return rejected("BAD_BOOKING", index);
        }
        const std::string key = oracleLower(oracleTrim(row.doctor));
        if (keys.count(key) == 0) {
            return rejected("BAD_BOOKING", index);
        }
        visits.push_back(OracleVisit{row.day, row.start, row.end, key});
    }
    if (!preferred.empty() && keys.count(preferred) == 0) {
        return rejected("UNKNOWN_DOCTOR");
    }
    if (given.requested_day < given.now_day || given.requested_day - given.now_day > 8) {
        return rejected("BAD_DAY_ORDER");
    }

    std::int64_t duration = 60;
    std::int64_t buffer = 15;
    if (kind == "checkup") {
        duration = 20;
        buffer = 5;
    } else if (kind == "consultation") {
        duration = 30;
        buffer = 10;
    }
    const std::int64_t last = std::min({given.requested_day + given.horizon_days,
                                        given.requested_day + 14,
                                        static_cast<std::int64_t>(1000000)});
    std::vector<OracleCandidate> found;
    for (std::int64_t day = given.requested_day; day <= last; day += 1) {
        if (holidays.count(day) != 0) {
            continue;
        }
        const std::int64_t weekday = day % 7;
        if (weekday == 6) {
            continue;
        }
        const std::int64_t open = weekday == 5 ? 600 : 540;
        const std::int64_t close = weekday == 5 ? 840 : 1020;
        for (const OracleDoctor& doctor : doctors) {
            if (!given.urgent && !preferred.empty() && doctor.key != preferred) {
                continue;
            }
            std::vector<OracleVisit> daily;
            for (const OracleVisit& visit : visits) {
                if (visit.day == day && visit.key == doctor.key) {
                    daily.push_back(visit);
                }
            }
            if (daily.size() >= 4) {
                continue;
            }
            for (std::int64_t start = 0; start <= 1435; start += 5) {
                const std::int64_t end = start + duration;
                const std::int64_t reserved_end = end + buffer;
                if (day == given.now_day && start < given.now_minute + 60) {
                    continue;
                }
                if (start < open || reserved_end > close) {
                    continue;
                }
                if (start < 780 && reserved_end > 720) {
                    continue;
                }
                bool inside_window = false;
                for (const Window& window : doctor.windows) {
                    if (window.weekday == weekday && window.open <= start &&
                        reserved_end <= window.close) {
                        inside_window = true;
                    }
                }
                if (!inside_window) {
                    continue;
                }
                bool clash = false;
                for (const OracleVisit& visit : daily) {
                    if (start < visit.end && visit.start < reserved_end) {
                        clash = true;
                    }
                }
                if (clash) {
                    continue;
                }
                found.push_back(
                    OracleCandidate{day, start, end, doctor.key, doctor.name});
            }
        }
    }
    if (found.empty()) {
        return rejected("NO_SLOT");
    }
    OracleCandidate best = found.front();
    for (const OracleCandidate& row : found) {
        const bool earlier_day = row.day < best.day;
        const bool same_day_earlier =
            row.day == best.day &&
            (row.start < best.start || (row.start == best.start && row.key < best.key));
        if (earlier_day || same_day_earlier) {
            best = row;
        }
    }
    return accepted(Slot{best.day, best.start, best.end, best.doctor, {}});
}

bool sameFailure(const Failure& left, const Failure& right) {
    if (left.code != right.code || left.has_index != right.has_index) {
        return false;
    }
    return !left.has_index || left.index == right.index;
}

bool sameSlot(const Slot& left, const Slot& right) {
    return left.day == right.day && left.start == right.start && left.end == right.end &&
           left.doctor == right.doctor && left.trace == right.trace;
}

bool sameOutcome(const Outcome& left, const Outcome& right) {
    if (left.failed != right.failed) {
        return false;
    }
    return left.failed ? sameFailure(left.error, right.error)
                       : sameSlot(left.slot, right.slot);
}

std::string describe(const Request& given) {
    std::string text = "now=(" + std::to_string(given.now_day) + "," +
                       std::to_string(given.now_minute) + ") requested=" +
                       std::to_string(given.requested_day) + " horizon=" +
                       std::to_string(given.horizon_days) + " kind=" + given.kind +
                       " urgent=" + (given.urgent ? "true" : "false") + " preferred=" +
                       given.preferred_doctor + " holidays[";
    for (std::size_t index = 0; index < given.holidays.size(); index += 1) {
        if (index > 0) {
            text += ",";
        }
        text += std::to_string(given.holidays[index]);
    }
    text += "] doctors[";
    for (const Doctor& doctor : given.doctors) {
        text += " " + doctor.name + ":" + std::to_string(doctor.windows.size()) + "w";
    }
    text += "] bookings[";
    for (const Booking& booking : given.bookings) {
        text += " " + std::to_string(booking.day) + "/" + std::to_string(booking.start) +
                "-" + std::to_string(booking.end) + "@" + booking.doctor;
    }
    return text + "]";
}

std::string describe(const Outcome& outcome) {
    if (outcome.failed) {
        std::string text = "error(" + outcome.error.code;
        if (outcome.error.has_index) {
            text += " at " + std::to_string(outcome.error.index);
        }
        return text + ")";
    }
    return "slot(" + std::to_string(outcome.slot.day) + "," +
           std::to_string(outcome.slot.start) + "-" + std::to_string(outcome.slot.end) +
           "," + outcome.slot.doctor + ",trace=" +
           std::to_string(outcome.slot.trace.size()) + ")";
}

void checkCase(const Request& given, const Outcome& wanted, const std::string& label) {
    const Outcome got = solution(given);
    if (sameOutcome(got, wanted)) {
        return;
    }
    std::cerr << label << ": expected " << describe(wanted) << " but got "
              << describe(got) << " for " << describe(given) << '\n';
    std::exit(1);
}

void checkOracle(const Request& given, const std::string& label) {
    checkCase(given, oracle(given), label + " (oracle)");
}

void check(const Request& given, const Outcome& wanted, const std::string& label) {
    checkCase(given, wanted, label);
    checkOracle(given, label);
}

Window window(std::int64_t weekday, std::int64_t open, std::int64_t close) {
    return Window{weekday, open, close};
}

std::vector<Window> weekdays(std::int64_t open, std::int64_t close) {
    std::vector<Window> windows;
    for (std::int64_t weekday = 0; weekday < 5; weekday += 1) {
        windows.push_back(window(weekday, open, close));
    }
    return windows;
}

Doctor doctor(const std::string& name, std::vector<Window> windows) {
    return Doctor{name, windows};
}

Booking booking(std::int64_t day, std::int64_t start, std::int64_t end,
                const std::string& who) {
    return Booking{day, start, end, who};
}

Request base() {
    Request request;
    request.now_day = 100;
    request.now_minute = 480;
    request.requested_day = 100;
    request.horizon_days = 2;
    request.kind = "checkup";
    request.urgent = false;
    request.doctors = {doctor("Ada", weekdays(540, 1020))};
    return request;
}

Request withDoctors(const Request& start, std::vector<Doctor> doctors) {
    Request request = start;
    request.doctors = doctors;
    return request;
}

Request withBookings(const Request& start, std::vector<Booking> bookings) {
    Request request = start;
    request.bookings = bookings;
    return request;
}

Request withHolidays(const Request& start, std::vector<std::int64_t> holidays) {
    Request request = start;
    request.holidays = holidays;
    return request;
}

Request withKind(const Request& start, const std::string& kind) {
    Request request = start;
    request.kind = kind;
    return request;
}

Request withNow(const Request& start, std::int64_t day, std::int64_t minute) {
    Request request = start;
    request.now_day = day;
    request.now_minute = minute;
    return request;
}

Request withDay(const Request& start, std::int64_t requested_day) {
    Request request = start;
    request.requested_day = requested_day;
    return request;
}

Request withHorizon(const Request& start, std::int64_t horizon_days) {
    Request request = start;
    request.horizon_days = horizon_days;
    return request;
}

Request withPreferred(const Request& start, const std::string& preferred) {
    Request request = start;
    request.preferred_doctor = preferred;
    return request;
}

Request withUrgent(const Request& start, bool urgent) {
    Request request = start;
    request.urgent = urgent;
    return request;
}

void checkWorkedExamples() {
    check(base(), result(100, 540, 560), "default request");
    check(withKind(base(), "  CONSULTATION  "), result(100, 540, 570),
          "kind trimmed and lowered");
    check(withNow(base(), 100, 500), result(100, 560, 580), "notice pushes one grid step");
    check(withNow(base(), 100, 1000), result(101, 540, 560),
          "notice skips the rest of the day");
    check(withKind(base(), "consultation"), result(100, 540, 570), "consultation duration");
    check(withKind(base(), "procedure"), result(100, 540, 600), "procedure duration");
    check(withDoctors(base(), {doctor("  Ada  ", {window(2, 600, 660)})}),
          result(100, 600, 620), "trimmed name and window lower bound");
    check(withDoctors(base(), {doctor("Ada", {window(2, 700, 840)})}),
          result(100, 780, 800), "lunch pushes the start past 780");
    check(withBookings(base(), {booking(100, 540, 570, "  ADA  ")}),
          result(100, 570, 590), "booking end is touched, not overlapped");
    check(withBookings(base(), {booking(100, 540, 565, "Ada")}), result(100, 565, 585),
          "reserved end touches the next start");
    check(withBookings(base(), {booking(100, 540, 550, "Ada"),
                                booking(100, 560, 570, "Ada"),
                                booking(100, 580, 590, "Ada"),
                                booking(100, 600, 610, "Ada")}),
          result(101, 540, 560), "daily cap moves to the next day");
    check(withHolidays(base(), {100}), result(101, 540, 560), "holiday is skipped");
    check(withDoctors(base(), {doctor("Bo", {window(2, 540, 1020)}),
                               doctor("Ada", {window(2, 540, 1020)})}),
          result(100, 540, 560), "doctor name decides a slot tie");
}

void checkValidationBoundaries() {
    check(withNow(base(), -1, 480), rejected("BAD_REQUEST"), "now_day below zero");
    check(withDoctors(base(), {}), rejected("BAD_DOCTORS"), "no doctors");
    check(withDoctors(base(), {doctor("Ada", {window(7, 540, 600)}),
                               doctor(" ada ", {})}),
          rejected("BAD_DOCTORS", 1), "duplicate name before window shape");
    check(withDoctors(base(), {doctor("Ada", {}), doctor("Bo", {}),
                               doctor("Cy", {window(2, 900, 900)})}),
          rejected("BAD_WINDOW", 2), "empty window range at doctor 2");
    check(withHolidays(base(), {100, 100}), rejected("BAD_HOLIDAY", 1),
          "duplicate holiday");
    check(withBookings(base(), {booking(100, 540, 550, "Ada"),
                                booking(100, 540, 540, "Ada")}),
          rejected("BAD_BOOKING", 1), "booking start equals end");
    check(withBookings(base(), {booking(100, 540, 550, "Ada"),
                                booking(100, 550, 560, "Ada"),
                                booking(100, 560, 560, "Ada")}),
          rejected("BAD_BOOKING", 2), "third booking start equals end");
    check(withPreferred(base(), "Bo"), rejected("UNKNOWN_DOCTOR"), "unknown preference");
    check(withDay(base(), 99), rejected("BAD_DAY_ORDER"), "requested day before now");
    check(withDay(base(), 109), rejected("BAD_DAY_ORDER"), "requested day past eight");
    check(withPreferred(withDay(base(), 109), "Bo"), rejected("UNKNOWN_DOCTOR"),
          "unknown doctor before day order");
    check(withKind(withDoctors(base(), {}), "other"), rejected("BAD_REQUEST"),
          "scalar check before the doctors count");
    check(withHolidays(withDoctors(base(), {doctor("Ada", {}), doctor("ada", {})}), {-1}),
          rejected("BAD_DOCTORS", 1), "duplicate doctors before bad holiday");
    check(withBookings(withHolidays(base(), {-1}), {booking(100, 540, 540, "Ada")}),
          rejected("BAD_HOLIDAY", 0), "bad holiday before bad booking");
    check(withHolidays(withDoctors(base(), {doctor("Ada", {window(2, 700, 700)})}), {-1}),
          rejected("BAD_WINDOW", 0), "bad window before bad holiday");
    check(withPreferred(withBookings(base(), {booking(100, 1, 1, "Ada")}), "Bo"),
          rejected("BAD_BOOKING", 0), "bad booking before unknown doctor");
    check(withDoctors(base(), {doctor("Ada", {window(1, 540, 1020)})}),
          rejected("NO_SLOT"), "Tuesday window never matches Wednesday to Friday");
    check(withHolidays(base(), {1000001}), rejected("BAD_HOLIDAY", 0),
          "holiday day 1000001");
    check(withDoctors(base(), {doctor("Ada", {window(2, 540, 1441)})}),
          rejected("BAD_WINDOW", 0), "window close 1441");
    check(withDoctors(base(), {doctor("Ada", {window(7, 540, 600)})}),
          rejected("BAD_WINDOW", 0), "weekday above six");
    check(withDoctors(base(), {doctor("", {})}), rejected("BAD_DOCTORS", 0),
          "empty doctor name");
    check(withBookings(base(), {booking(100, 540, 1441, "Ada")}),
          rejected("BAD_BOOKING", 0), "booking end 1441");
    check(withBookings(base(), {booking(1000001, 540, 550, "Ada")}),
          rejected("BAD_BOOKING", 0), "booking day 1000001");
    check(withBookings(base(), {booking(100, 540, 550, "Ghost")}),
          rejected("BAD_BOOKING", 0), "booking names an unknown doctor");
    check(withDoctors(base(), {doctor("Ada@", {})}), rejected("BAD_DOCTORS", 0),
          "name syntax");
    check(withDoctors(base(), {doctor("Doc 0-1", {window(2, 540, 1020)})}),
          result(100, 540, 560, "Doc 0-1"), "spaces and hyphens are legal");
    check(withHorizon(base(), 15), rejected("BAD_REQUEST"), "horizon 15");
    check(withNow(base(), 100, 1440), rejected("BAD_REQUEST"), "minute 1440");
    check(withDay(base(), 1000001), rejected("BAD_REQUEST"), "requested day 1000001");
    check(withUrgent(withPreferred(withDay(base(), 109), "Zed"), true),
          rejected("UNKNOWN_DOCTOR"), "urgent keeps preference validation");
    check(withKind(base(), "other"), rejected("BAD_REQUEST"), "unknown kind");

    std::vector<Doctor> thirteen;
    for (int index = 0; index < 13; index += 1) {
        thirteen.push_back(doctor("D" + std::to_string(index), {}));
    }
    check(withDoctors(base(), thirteen), rejected("BAD_DOCTORS"), "thirteen doctors");

    std::vector<std::int64_t> many_holidays;
    for (std::int64_t day = 0; day < 61; day += 1) {
        many_holidays.push_back(day);
    }
    check(withHolidays(base(), many_holidays), rejected("BAD_HOLIDAY"),
          "sixty one holidays");

    std::vector<Booking> many_bookings;
    for (std::int64_t index = 0; index < 201; index += 1) {
        many_bookings.push_back(booking(500 + index, 0, 1, "Ada"));
    }
    check(withBookings(base(), many_bookings), rejected("BAD_BOOKING"),
          "two hundred one bookings");

    std::vector<Window> nine_windows;
    for (int index = 0; index < 9; index += 1) {
        nine_windows.push_back(window(2, 540, 600));
    }
    check(withDoctors(base(), {doctor("Ada", nine_windows)}), rejected("BAD_WINDOW", 0),
          "nine windows");
}

void checkSchedulingBoundaries() {
    for (const std::int64_t minute : {599, 600, 655}) {
        checkOracle(withDoctors(base(), {doctor("Ada", {window(2, minute, 685)})}),
                    "window bound " + std::to_string(minute));
    }
    check(withNow(base(), 100, 480), result(100, 540, 560), "notice exactly satisfied");
    check(withNow(base(), 100, 481), result(100, 545, 565), "notice 59 is too early");
    check(withHorizon(base(), 0), result(100, 540, 560), "horizon zero");
    check(withHolidays(withHorizon(base(), 0), {100}), rejected("NO_SLOT"),
          "horizon zero with one holiday");
    Request day_zero = withNow(base(), 0, 0);
    day_zero = withDay(day_zero, 0);
    day_zero = withHorizon(day_zero, 0);
    check(day_zero, result(0, 540, 560), "day zero");
    check(withDoctors(base(), {doctor("Ada", {})}), rejected("NO_SLOT"),
          "doctor without windows");
    check(withDay(base(), 108), result(108, 540, 560), "requested day is now plus eight");
    check(withDay(base(), 102), result(102, 540, 560), "Friday is open");
    check(withDoctors(base(), {doctor("Ada", {window(5, 600, 840)})}),
          rejected("NO_SLOT"), "weekday window must match");
    check(withDoctors(base(), {doctor("Ada", {window(2, 540, 565)})}),
          result(100, 540, 560), "reserved end equals window close");
    check(withDoctors(base(), {doctor("Ada", {window(2, 600, 625)})}),
          result(100, 600, 620), "window exactly holds one appointment");
    check(withDoctors(base(), {doctor("Ada", {window(2, 540, 564)})}),
          rejected("NO_SLOT"), "window one minute short");
    check(withDoctors(base(), {doctor("Ada", {window(2, 500, 600)})}),
          result(100, 540, 560), "window opens before the clinic does");
    check(withBookings(base(), {booking(100, 540, 695, "Ada")}), result(100, 695, 715),
          "booking end 695 touches lunch");
    check(withBookings(base(), {booking(100, 540, 696, "Ada")}), result(100, 780, 800),
          "booking end 696 pushes past lunch");
    check(withDoctors(base(), {doctor("Ada", {window(2, 995, 1020)})}),
          result(100, 995, 1015), "late window start on the grid");
    check(withBookings(base(), {booking(100, 540, 555, "Ada")}), result(100, 555, 575),
          "booking end 555 is on the grid");
    check(withBookings(base(), {booking(100, 565, 575, "Ada")}), result(100, 540, 560),
          "booking starts after the first slot");
    check(withDoctors(base(), {doctor("Ada", {window(2, 575, 600)})}),
          result(100, 575, 595), "window starts on the grid");
    check(withDoctors(base(), {doctor("zoe", {window(2, 540, 1020)}),
                               doctor("ada", {window(2, 540, 1020)})}),
          result(100, 540, 560, "ada"), "lowercase names sort by key");
    check(withDoctors(base(), {doctor("BO", {window(2, 540, 1020)}),
                               doctor("ada", {window(2, 540, 1020)})}),
          result(100, 540, 560, "ada"), "uppercase name keeps its spelling");
    check(withPreferred(base(), " ada "), result(100, 540, 560),
          "preferred doctor trimmed");
    check(withBookings(base(), {booking(100, 0, 1, "ada")}), result(100, 540, 560),
          "booking doctor normalised");
    check(withHolidays(base(), {100, 101}), result(102, 540, 560),
          "two holidays skipped");
    check(withNow(base(), 100, 1439), result(101, 540, 560), "last minute of the day");
    check(withHorizon(base(), 14), result(100, 540, 560), "maximum horizon");
    check(withBookings(base(), {booking(100, 800, 810, "Ada"),
                                booking(100, 850, 860, "Ada"),
                                booking(100, 900, 910, "Ada")}),
          result(100, 540, 560), "late bookings do not disturb the first slot");

    Request priority = withDoctors(base(), {doctor("Bo", {window(2, 540, 1020)}),
                                            doctor("Ada", {window(2, 540, 1020)})});
    priority = withPreferred(priority, "Bo");
    check(priority, result(100, 540, 560, "Bo"), "preference wins for nonurgent");
    check(withUrgent(priority, true), result(100, 540, 560, "Ada"),
          "urgent ignores the preference");

    Request capped = withDoctors(base(), {doctor("Ada", {window(2, 540, 1020)}),
                                          doctor("Bo", {window(2, 540, 1020)})});
    capped = withBookings(capped, {booking(100, 800, 810, "Ada"),
                                   booking(100, 820, 830, "Ada"),
                                   booking(100, 840, 850, "Ada"),
                                   booking(100, 860, 870, "Ada")});
    check(capped, result(100, 540, 560, "Bo"), "capped doctor falls back");

    Request capped_none = withDoctors(base(), {doctor("Ada", {window(2, 800, 900)})});
    capped_none = withHorizon(capped_none, 0);
    capped_none = withBookings(capped_none, {booking(100, 540, 550, "Ada"),
                                             booking(100, 560, 570, "Ada"),
                                             booking(100, 580, 590, "Ada"),
                                             booking(100, 600, 610, "Ada")});
    check(capped_none, rejected("NO_SLOT"), "capped doctor with no fallback");

    Request saturday = withDoctors(base(), {doctor("Ada", {window(5, 600, 840)})});
    saturday = withDay(saturday, 103);
    saturday = withHorizon(saturday, 0);
    check(saturday, result(103, 600, 620), "Saturday opens at 600");

    Request saturday_wide = withDoctors(base(), {doctor("Ada", {window(5, 600, 900)})});
    saturday_wide = withDay(saturday_wide, 103);
    saturday_wide = withHorizon(saturday_wide, 0);
    check(saturday_wide, result(103, 600, 620), "Saturday window clamps to 840");

    Request saturday_open = withDoctors(base(), {doctor("Ada", {window(5, 540, 1020)})});
    saturday_open = withDay(saturday_open, 103);
    saturday_open = withHorizon(saturday_open, 0);
    check(saturday_open, result(103, 600, 620), "Saturday opening is 600");

    Request sunday = withDoctors(base(), {doctor("Ada", {window(6, 540, 1020)})});
    sunday = withDay(sunday, 104);
    sunday = withHorizon(sunday, 0);
    check(sunday, rejected("NO_SLOT"), "Sunday is closed");

    Request saturday_clamp = withDoctors(base(), {doctor("Ada", {window(5, 600, 900)})});
    saturday_clamp = withDay(saturday_clamp, 103);
    saturday_clamp = withHorizon(saturday_clamp, 0);
    saturday_clamp = withBookings(saturday_clamp, {booking(103, 600, 835, "Ada")});
    check(saturday_clamp, rejected("NO_SLOT"), "Saturday closes at 840");

    check(withDoctors(base(), {doctor("Ada", {window(2, 1000, 1100)})}),
          rejected("NO_SLOT"), "weekday clinic closes at 1020");

    Request late_window = withDoctors(base(), {doctor("Ada", {window(2, 900, 1100)})});
    late_window = withBookings(late_window, {booking(100, 900, 1000, "Ada")});
    check(late_window, rejected("NO_SLOT"),
          "window past closing with the earlier slots blocked");
    check(withDoctors(base(), {doctor("Ada", {window(2, 800, 900)}),
                               doctor("Bo", {window(2, 540, 1020)})}),
          result(100, 540, 560, "Bo"), "earliest start beats doctor order");

    std::vector<std::int64_t> fortnight;
    for (std::int64_t day = 100; day < 114; day += 1) {
        fortnight.push_back(day);
    }
    Request last_day = withHolidays(base(), fortnight);
    last_day = withHorizon(last_day, 14);
    last_day = withDoctors(last_day, {doctor("Ada", {window(2, 540, 1020)})});
    check(last_day, result(114, 540, 560), "slot only on the last horizon day");

    Request last_cap = withNow(base(), 999992, 480);
    last_cap = withDay(last_cap, 1000000);
    last_cap = withHorizon(last_cap, 14);
    check(last_cap, result(1000000, 540, 560), "day cap 1000000 is a candidate");
    check(withHolidays(last_cap, {1000000}), rejected("NO_SLOT"),
          "day cap with a holiday");

    std::vector<Window> eight_windows;
    for (int index = 0; index < 8; index += 1) {
        eight_windows.push_back(window(2, 540, 1020));
    }
    check(withDoctors(base(), {doctor("Ada", eight_windows)}), result(100, 540, 560),
          "eight windows accepted");

    std::vector<std::int64_t> sixty_holidays;
    for (std::int64_t day = 200; day < 260; day += 1) {
        sixty_holidays.push_back(day);
    }
    check(withHolidays(base(), sixty_holidays), result(100, 540, 560),
          "sixty holidays accepted");

    std::vector<Booking> two_hundred;
    for (std::int64_t index = 0; index < 200; index += 1) {
        two_hundred.push_back(booking(500 + index, 0, 1, "Ada"));
    }
    check(withBookings(base(), two_hundred), result(100, 540, 560),
          "two hundred bookings accepted");

    std::vector<Doctor> twelve;
    for (int index = 0; index < 12; index += 1) {
        twelve.push_back(doctor("Doc " + std::to_string(index), {window(2, 540, 1020)}));
    }
    check(withDoctors(base(), twelve), result(100, 540, 560, "Doc 0"),
          "twelve doctors accepted");
}

std::uint64_t nextMixed(std::uint64_t& state) {
    state += 0x9E3779B97F4A7C15ULL;
    std::uint64_t z = state;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

std::size_t pickBounded(std::uint64_t& state, std::size_t count) {
    return static_cast<std::size_t>(nextMixed(state) % count);
}

void require(bool condition, const std::string& message) {
    if (condition) {
        return;
    }
    std::cerr << "random diversity: " << message << '\n';
    std::exit(1);
}

void printCounts(const std::string& label, const std::map<std::string, int>& counts) {
    std::cout << label << ':';
    for (const auto& entry : counts) {
        std::cout << ' ' << entry.first << '=' << entry.second;
    }
    std::cout << '\n';
}

void applyFault(std::uint64_t& state, Request& given) {
    if (pickBounded(state, 100) >= 25) {
        return;
    }
    switch (pickBounded(state, 16)) {
        case 0:
            given.now_day = 1000001;
            break;
        case 1:
            given.horizon_days = 15;
            break;
        case 2:
            given.now_minute = 1440;
            break;
        case 3:
            given.kind = "other";
            break;
        case 4:
            given.doctors.clear();
            break;
        case 5: {
            const std::string first = given.doctors.front().name;
            given.doctors.push_back(Doctor{first, {}});
            break;
        }
        case 6:
            given.doctors.front().name = "Ada@";
            break;
        case 7:
            given.doctors.front().windows = {Window{7, 540, 600}};
            break;
        case 8:
            given.holidays.push_back(-1);
            break;
        case 9:
            given.holidays.clear();
            for (std::int64_t day = 0; day < 61; day += 1) {
                given.holidays.push_back(day);
            }
            break;
        case 10:
            given.bookings.push_back(
                Booking{given.requested_day, 540, 540, given.doctors.front().name});
            break;
        case 11:
            given.bookings.push_back(Booking{given.requested_day, 540, 550, "Ghost"});
            break;
        case 12:
            given.bookings.clear();
            for (std::int64_t index = 0; index < 201; index += 1) {
                given.bookings.push_back(
                    Booking{500 + index, 0, 1, given.doctors.front().name});
            }
            break;
        case 13:
            given.preferred_doctor = "Zed";
            break;
        case 14:
            given.requested_day = given.now_day + 9;
            break;
        default:
            for (Doctor& row : given.doctors) {
                row.windows.clear();
            }
            break;
    }
}

std::string signature(const Request& given) {
    std::string text = std::to_string(given.now_day) + '/' +
                       std::to_string(given.now_minute) + '/' +
                       std::to_string(given.requested_day) + '/' +
                       std::to_string(given.horizon_days) + '/' + given.kind + '/' +
                       (given.urgent ? "1" : "0") + '/' + given.preferred_doctor;
    for (const std::int64_t day : given.holidays) {
        text += '/' + std::to_string(day);
    }
    for (const Doctor& doctor : given.doctors) {
        text += '|' + doctor.name + ':' + std::to_string(doctor.windows.size());
    }
    for (const Booking& booking : given.bookings) {
        text += ';' + std::to_string(booking.day) + '/' + std::to_string(booking.start) +
                '-' + std::to_string(booking.end) + '@' + booking.doctor;
    }
    return text;
}

void checkRandomCases() {
    const char* names[] = {"Ada", "Bo", "Cy"};
    const char* kinds[] = {"checkup", "consultation", "procedure"};
    const std::int64_t lengths[] = {10, 20, 30, 60};

    std::uint64_t state = 20261018ULL;
    std::map<std::string, int> kind_counts;
    std::map<std::string, int> urgent_counts;
    std::map<std::string, int> doctor_counts;
    std::map<std::string, int> offset_counts;
    std::map<std::string, int> error_counts;
    std::set<std::string> seen;
    int valid = 0;
    int booked = 0;
    const int rounds = 2000;
    for (int round = 0; round < rounds; round += 1) {
        const std::int64_t now_day =
            20 + static_cast<std::int64_t>(pickBounded(state, 881));
        const std::int64_t offset = static_cast<std::int64_t>(pickBounded(state, 9));
        const std::int64_t horizon = static_cast<std::int64_t>(pickBounded(state, 15));
        const std::int64_t first_day = now_day + offset;
        const std::size_t doctor_count = 1 + pickBounded(state, 3);
        const std::size_t day_span = static_cast<std::size_t>(horizon + 1);
        std::vector<Doctor> doctors;
        for (std::size_t position = 0; position < doctor_count; position += 1) {
            std::vector<Window> windows;
            for (std::int64_t weekday = 0; weekday < 7; weekday += 1) {
                if (pickBounded(state, 4) == 0) {
                    continue;
                }
                const bool saturday = weekday == 5;
                windows.push_back(
                    window(weekday, saturday ? 600 : 540, saturday ? 840 : 1020));
            }
            doctors.push_back(Doctor{names[position], windows});
        }
        std::vector<Booking> bookings;
        const std::size_t booking_count = pickBounded(state, 17);
        for (std::size_t position = 0; position < booking_count; position += 1) {
            const std::string& who = doctors[pickBounded(state, doctor_count)].name;
            const std::int64_t start =
                540 + 5 * static_cast<std::int64_t>(pickBounded(state, 84));
            const std::int64_t end = std::min(
                start + lengths[pickBounded(state, 4)], static_cast<std::int64_t>(1440));
            const std::int64_t day =
                first_day + static_cast<std::int64_t>(pickBounded(state, day_span));
            bookings.push_back(Booking{day, start, end, who});
            if (pickBounded(state, 4) == 0 && end + 10 <= 960) {
                bookings.push_back(Booking{day, end, end + 10, who});
            }
        }
        if (pickBounded(state, 3) == 0) {
            const std::string& who = doctors[pickBounded(state, doctor_count)].name;
            const std::int64_t day =
                first_day + static_cast<std::int64_t>(pickBounded(state, day_span));
            for (std::int64_t minute = 0; minute < 4; minute += 1) {
                bookings.push_back(Booking{day, minute, minute + 1, who});
            }
        }
        std::set<std::int64_t> holiday_set;
        const std::size_t holiday_count = pickBounded(state, 4);
        for (std::size_t position = 0; position < holiday_count; position += 1) {
            holiday_set.insert(
                first_day + static_cast<std::int64_t>(pickBounded(state, day_span)));
        }
        Request given = base();
        given.now_day = now_day;
        given.now_minute = static_cast<std::int64_t>(pickBounded(state, 1440));
        given.requested_day = first_day;
        given.horizon_days = horizon;
        given.kind = kinds[pickBounded(state, 3)];
        given.urgent = pickBounded(state, 2) == 1;
        given.preferred_doctor = pickBounded(state, 3) == 0
                                     ? ""
                                     : doctors[pickBounded(state, doctor_count)].name;
        given.holidays.assign(holiday_set.begin(), holiday_set.end());
        given.doctors = doctors;
        given.bookings = bookings;
        offset_counts[std::to_string(first_day - now_day)] += 1;
        doctor_counts[std::to_string(doctor_count)] += 1;
        urgent_counts[given.urgent ? "true" : "false"] += 1;
        applyFault(state, given);

        const Outcome wanted = oracle(given);
        checkCase(given, wanted, "random case " + std::to_string(round));
        seen.insert(signature(given));
        if (!given.bookings.empty()) {
            booked += 1;
        }
        if (wanted.failed) {
            error_counts[wanted.error.code] += 1;
        } else {
            valid += 1;
            kind_counts[oracleLower(oracleTrim(given.kind))] += 1;
        }
    }

    std::cout << "random: " << rounds << " cases, " << valid << " valid, " << booked
              << " with bookings, " << seen.size() << " distinct\n";
    printCounts("kinds", kind_counts);
    printCounts("urgent", urgent_counts);
    printCounts("doctors", doctor_counts);
    printCounts("offsets", offset_counts);
    printCounts("errors", error_counts);

    require(valid * 2 >= rounds, "fewer than half of the random cases are valid");
    require(booked * 2 >= rounds, "fewer than half of the random cases carry bookings");
    require(seen.size() * 2 >= static_cast<std::size_t>(rounds), "random requests repeat");
    for (const char* name : {"checkup", "consultation", "procedure"}) {
        require(kind_counts[name] > 0, std::string("kind missing: ") + name);
    }
    require(urgent_counts["true"] > 0 && urgent_counts["false"] > 0,
            "both urgency values must appear");
    require(doctor_counts["1"] > 0 && doctor_counts["2"] > 0 && doctor_counts["3"] > 0,
            "one, two and three doctors must appear");
    for (int offset = 0; offset <= 8; offset += 1) {
        require(offset_counts[std::to_string(offset)] > 0,
                "day offset missing: " + std::to_string(offset));
    }
    for (const char* code :
         {"BAD_REQUEST", "BAD_DOCTORS", "BAD_WINDOW", "BAD_HOLIDAY", "BAD_BOOKING",
          "UNKNOWN_DOCTOR", "BAD_DAY_ORDER", "NO_SLOT"}) {
        require(error_counts[code] > 0, std::string("error missing: ") + code);
    }
}

int main() {
    if (std::getenv("CLINIC_BOOKING_RANDOM_ONLY") == nullptr) {
        checkWorkedExamples();
        checkValidationBoundaries();
        checkSchedulingBoundaries();
    }
    checkRandomCases();
    return 0;
}
