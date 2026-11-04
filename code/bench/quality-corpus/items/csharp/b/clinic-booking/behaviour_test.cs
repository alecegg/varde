using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

// Every value is a plain-data record, so a request row reads as one expression.
Solution.Doctor Doctor(string name, params (int Weekday, int Open, int Close)[] windows) =>
    new(name, windows.Select(row => new Solution.Window(row.Weekday, row.Open, row.Close))
        .ToArray());

Solution.Booking Booking(int day, int start, int end, string doctor) =>
    new(day, start, end, doctor);

Solution.Request Base() => new(
    100,
    480,
    100,
    2,
    "checkup",
    false,
    "",
    Array.Empty<int>(),
    new[] { Doctor("Ada", (0, 540, 1020), (1, 540, 1020), (2, 540, 1020), (3, 540, 1020),
        (4, 540, 1020)) },
    Array.Empty<Solution.Booking>());

Solution.Appointment Result(int day, int start, int end, string doctor = "Ada") => new(
    day,
    start,
    end,
    doctor,
    new[]
    {
        "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
        "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
        "earliest-grid-slot"
    });

Solution.ClinicError Error(string code, int? index = null) => new(code, index);

void Check(Solution.Request request, Solution.Outcome expected)
{
    Solution.Outcome actual = Solution.solution(request);
    string actualJson = JsonSerializer.Serialize(actual, actual.GetType());
    string expectedJson = JsonSerializer.Serialize(expected, expected.GetType());
    if (actualJson != expectedJson)
    {
        throw new InvalidOperationException($"{JsonSerializer.Serialize(request)}\n"
            + $"expected {expectedJson}\nactual   {actualJson}");
    }
}

// A deliberately brute-force oracle: validate, then inspect every day, doctor and
// five-minute start, sort the surviving triples and take the first one.
bool InvalidName(string name) =>
    name.Length == 0 || name.Any(letter => !(char.IsAsciiLetterOrDigit(letter)
        || letter == ' ' || letter == '-'));

Solution.Outcome Oracle(Solution.Request request)
{
    string kind = request.Kind.Trim(' ').ToLowerInvariant();
    if (request.NowDay < 0 || request.NowDay > 1_000_000
        || request.RequestedDay < 0 || request.RequestedDay > 1_000_000
        || request.NowMinute < 0 || request.NowMinute > 1439
        || request.HorizonDays < 0 || request.HorizonDays > 14
        || kind is not ("checkup" or "consultation" or "procedure"))
        return Error("BAD_REQUEST");
    if (request.Doctors.Length < 1 || request.Doctors.Length > 12)
        return Error("BAD_DOCTORS");
    string[] names = request.Doctors
        .Select(doctor => doctor.Name.Trim(' ').ToLowerInvariant()).ToArray();
    for (int index = 0; index < names.Length; index++)
    {
        if (InvalidName(names[index]) || names.Take(index).Contains(names[index]))
            return Error("BAD_DOCTORS", index);
    }
    for (int index = 0; index < request.Doctors.Length; index++)
    {
        Solution.Window[] windows = request.Doctors[index].Windows;
        if (windows.Length > 8 || windows.Any(window => window.Weekday < 0
            || window.Weekday > 6 || window.Open < 0 || window.Open >= window.Close
            || window.Close > 1440))
            return Error("BAD_WINDOW", index);
    }
    if (request.Holidays.Length > 60) return Error("BAD_HOLIDAY");
    for (int index = 0; index < request.Holidays.Length; index++)
    {
        int closed = request.Holidays[index];
        if (closed < 0 || closed > 1_000_000 || request.Holidays.Take(index).Contains(closed))
            return Error("BAD_HOLIDAY", index);
    }
    if (request.Bookings.Length > 200) return Error("BAD_BOOKING");
    for (int index = 0; index < request.Bookings.Length; index++)
    {
        Solution.Booking row = request.Bookings[index];
        string owner = row.Doctor.Trim(' ').ToLowerInvariant();
        if (row.Day < 0 || row.Day > 1_000_000 || row.Start < 0 || row.Start >= row.End
            || row.End > 1440 || !names.Contains(owner))
            return Error("BAD_BOOKING", index);
    }
    string preferred = request.PreferredDoctor.Trim(' ').ToLowerInvariant();
    if (preferred.Length > 0 && !names.Contains(preferred)) return Error("UNKNOWN_DOCTOR");
    if (request.RequestedDay < request.NowDay || request.RequestedDay - request.NowDay > 8)
        return Error("BAD_DAY_ORDER");
    (int Duration, int Buffer) length = kind switch
    {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15)
    };
    int last = Math.Min(
        Math.Min(request.RequestedDay + request.HorizonDays, request.RequestedDay + 14),
        1_000_000);
    var valid = new List<(int Day, int Start, string Key, string Doctor, int End)>();
    for (int day = request.RequestedDay; day <= last; day++)
    {
        if (request.Holidays.Contains(day)) continue;
        int weekday = day % 7;
        (int Open, int Close) hours = weekday < 5 ? (540, 1020)
            : weekday == 5 ? (600, 840) : (0, 0);
        for (int index = 0; index < request.Doctors.Length; index++)
        {
            string key = names[index];
            if (!request.Urgent && preferred.Length > 0 && key != preferred) continue;
            string owner = request.Doctors[index].Name.Trim(' ');
            var daily = request.Bookings.Where(row => row.Day == day
                && row.Doctor.Trim(' ').Equals(owner, StringComparison.OrdinalIgnoreCase))
                .ToList();
            for (int start = 0; start <= 1435; start += 5)
            {
                int end = start + length.Duration;
                int reservedEnd = end + length.Buffer;
                bool notified = day > request.NowDay || start >= request.NowMinute + 60;
                bool inHours = start >= hours.Open && reservedEnd <= hours.Close
                    && !(start < 780 && reservedEnd > 720);
                bool windowed = request.Doctors[index].Windows.Any(window =>
                    window.Weekday == weekday && window.Open <= start
                    && reservedEnd <= window.Close);
                bool clear = !daily.Any(row => start < row.End && row.Start < reservedEnd);
                if (notified && inHours && windowed && daily.Count < 4 && clear)
                    valid.Add((day, start, key, owner, end));
            }
        }
    }
    if (valid.Count == 0) return Error("NO_SLOT");
    var best = valid.OrderBy(slot => slot.Day).ThenBy(slot => slot.Start)
        .ThenBy(slot => slot.Key, StringComparer.Ordinal).First();
    return Result(best.Day, best.Start, best.End, best.Doctor);
}

void MatchOracle(Solution.Request request) => Check(request, Oracle(request));

var pinned = new (Solution.Request Input, Solution.Appointment Expected)[]
{
    (Base(), Result(100, 540, 560)),
    (Base() with { Kind = "  CONSULTATION  " }, Result(100, 540, 570)),
    (Base() with { NowMinute = 500 }, Result(100, 560, 580)),
    (Base() with { NowMinute = 481 }, Result(100, 545, 565)),
    (Base() with { NowMinute = 1000 }, Result(101, 540, 560)),
    (Base() with { NowMinute = 1439 }, Result(101, 540, 560)),
    (Base() with { Kind = "consultation" }, Result(100, 540, 570)),
    (Base() with { Kind = "procedure" }, Result(100, 540, 600)),
    (Base() with { Doctors = new[] { Doctor("  Ada  ", (2, 600, 660)) } },
        Result(100, 600, 620)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 700, 840)) } },
        Result(100, 780, 800)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 696, 1020)) } },
        Result(100, 780, 800)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 599, 685)) } },
        Result(100, 600, 620)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 655, 685)) } },
        Result(100, 655, 675)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 540, 565)) } },
        Result(100, 540, 560)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 600, 625)) } },
        Result(100, 600, 620)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 995, 1020)) } },
        Result(100, 995, 1015)),
    (Base() with { Bookings = new[] { Booking(100, 540, 570, "  ADA  ") } },
        Result(100, 570, 590)),
    (Base() with { Bookings = new[] { Booking(100, 540, 565, "Ada") } },
        Result(100, 565, 585)),
    (Base() with { Bookings = new[] { Booking(100, 540, 695, "Ada") } },
        Result(100, 695, 715)),
    (Base() with
    {
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Result(101, 540, 560)),
    (Base() with
    {
        Bookings = new[] { 800, 820, 840 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Result(100, 540, 560)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 540, 1020)), Doctor("Bo", (2, 540, 1020)) },
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Result(100, 540, 560, "Bo")),
    (Base() with { Holidays = new[] { 100 } }, Result(101, 540, 560)),
    (Base() with { Holidays = new[] { 100, 101 } }, Result(102, 540, 560)),
    (Base() with
    {
        Doctors = new[] { Doctor("Bo", (2, 540, 1020)), Doctor("Ada", (2, 540, 1020)) }
    }, Result(100, 540, 560)),
    (Base() with
    {
        Doctors = new[] { Doctor("zoe", (2, 540, 1020)), Doctor("ada", (2, 540, 1020)) }
    }, Result(100, 540, 560, "ada")),
    (Base() with
    {
        Doctors = new[] { Doctor("BO", (2, 540, 1020)), Doctor("ada", (2, 540, 1020)) }
    }, Result(100, 540, 560, "ada")),
    (Base() with
    {
        Doctors = new[]
        {
            Doctor("Doc 9", (2, 540, 1020)), Doctor("Doc 10", (2, 540, 1020))
        }
    }, Result(100, 540, 560, "Doc 10")),
    (Base() with
    {
        PreferredDoctor = "Bo",
        Doctors = new[] { Doctor("Bo", (2, 540, 1020)), Doctor("Ada", (2, 540, 1020)) }
    }, Result(100, 540, 560, "Bo")),
    (Base() with
    {
        PreferredDoctor = "Bo",
        Urgent = true,
        Doctors = new[] { Doctor("Bo", (2, 540, 1020)), Doctor("Ada", (2, 540, 1020)) }
    }, Result(100, 540, 560, "Ada")),
    (Base() with { PreferredDoctor = " ada " }, Result(100, 540, 560)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 800, 900)), Doctor("Bo", (2, 540, 1020)) },
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 30, "Bo")).ToArray()
    }, Result(100, 800, 820)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 540, 1020)), Doctor("Bo", (2, 540, 1020)) },
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Result(100, 540, 560, "Bo")),
    (Base() with { HorizonDays = 0 }, Result(100, 540, 560)),
    (Base() with { HorizonDays = 14 }, Result(100, 540, 560)),
    (Base() with
    {
        HorizonDays = 14,
        Holidays = Enumerable.Range(100, 14).ToArray()
    }, Result(114, 540, 560)),
    (Base() with { HorizonDays = 0, RequestedDay = 102 }, Result(102, 540, 560)),
    (Base() with
    {
        HorizonDays = 0,
        RequestedDay = 103,
        Doctors = new[] { Doctor("Ada", (5, 600, 840)) }
    }, Result(103, 600, 620)),
    (Base() with
    {
        HorizonDays = 0,
        RequestedDay = 103,
        Doctors = new[] { Doctor("Ada", (5, 815, 840)) }
    }, Result(103, 815, 835)),
    (Base() with { NowDay = 100, RequestedDay = 108, HorizonDays = 0 },
        Result(108, 540, 560)),
    (Base() with { NowDay = 0, NowMinute = 0, RequestedDay = 0, HorizonDays = 0 },
        Result(0, 540, 560)),
    (Base() with
    {
        NowDay = 999_999,
        RequestedDay = 1_000_000,
        HorizonDays = 14
    }, Result(1_000_000, 540, 560)),
    (Base() with { Bookings = new[] { Booking(100, 0, 1, "ada") } },
        Result(100, 540, 560)),
    (Base() with { Doctors = new[] { Doctor("Ada", (2, 540, 1020), (2, 540, 1020),
        (2, 540, 1020), (2, 540, 1020), (2, 540, 1020), (2, 540, 1020), (2, 540, 1020),
        (2, 540, 1020)) } }, Result(100, 540, 560)),
    (Base() with { Holidays = Enumerable.Range(200, 60).ToArray() },
        Result(100, 540, 560)),
    (Base() with
    {
        Bookings = Enumerable.Range(0, 200)
            .Select(offset => Booking(500 + offset, 0, 1, "Ada")).ToArray()
    }, Result(100, 540, 560)),
    (Base() with
    {
        Doctors = Enumerable.Range(0, 12)
            .Select(number => Doctor($"Doc {number}", (2, 540, 1020))).ToArray()
    }, Result(100, 540, 560, "Doc 0")),
};

var failures = new (Solution.Request Input, Solution.ClinicError Expected)[]
{
    (Base() with { NowDay = -1 }, Error("BAD_REQUEST")),
    (Base() with { NowDay = 1_000_001 }, Error("BAD_REQUEST")),
    (Base() with { NowMinute = 1440 }, Error("BAD_REQUEST")),
    (Base() with { HorizonDays = 15 }, Error("BAD_REQUEST")),
    (Base() with { RequestedDay = 1_000_001 }, Error("BAD_REQUEST")),
    (Base() with { Kind = "other", Doctors = Array.Empty<Solution.Doctor>() },
        Error("BAD_REQUEST")),
    (Base() with { Doctors = Array.Empty<Solution.Doctor>() }, Error("BAD_DOCTORS")),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (7, 540, 600)), Doctor(" ada ") }
    }, Error("BAD_DOCTORS", 1)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (7, 540, 600)) }
    }, Error("BAD_WINDOW", 0)),
    (Base() with { Doctors = new[] { Doctor("Ada@") } }, Error("BAD_DOCTORS", 0)),
    (Base() with
    {
        Doctors = Enumerable.Range(0, 13).Select(number => Doctor($"D{number}")).ToArray()
    }, Error("BAD_DOCTORS")),
    (Base() with
    {
        Doctors = new[]
        {
            Doctor("Ada"), Doctor("Bo"), Doctor("Cy", (2, 900, 900))
        }
    }, Error("BAD_WINDOW", 2)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 540, 1441)) }
    }, Error("BAD_WINDOW", 0)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 700, 700)) },
        Holidays = new[] { -1 }
    }, Error("BAD_WINDOW", 0)),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada", (2, 540, 600), (2, 540, 600), (2, 540, 600),
            (2, 540, 600), (2, 540, 600), (2, 540, 600), (2, 540, 600), (2, 540, 600),
            (2, 540, 600)) }
    }, Error("BAD_WINDOW", 0)),
    (Base() with { Holidays = new[] { 100, 100 } }, Error("BAD_HOLIDAY", 1)),
    (Base() with { Holidays = new[] { 1_000_001 } }, Error("BAD_HOLIDAY", 0)),
    (Base() with { Holidays = Enumerable.Range(0, 61).ToArray() }, Error("BAD_HOLIDAY")),
    (Base() with
    {
        Bookings = new[] { Booking(100, 540, 550, "Ada"), Booking(100, 540, 540, "Ada") }
    }, Error("BAD_BOOKING", 1)),
    (Base() with
    {
        Bookings = new[]
        {
            Booking(100, 540, 550, "Ada"), Booking(100, 550, 560, "Ada"),
            Booking(100, 560, 560, "Ada")
        }
    }, Error("BAD_BOOKING", 2)),
    (Base() with { Bookings = new[] { Booking(100, 540, 550, "Missing") } },
        Error("BAD_BOOKING", 0)),
    (Base() with { Bookings = new[] { Booking(100, 540, 1441, "Ada") } },
        Error("BAD_BOOKING", 0)),
    (Base() with { Bookings = new[] { Booking(100, 540, 540, "Ada") } },
        Error("BAD_BOOKING", 0)),
    (Base() with { Bookings = new[] { Booking(1_000_001, 540, 550, "Ada") } },
        Error("BAD_BOOKING", 0)),
    (Base() with { Bookings = new[] { Booking(-1, 540, 550, "Ada") } },
        Error("BAD_BOOKING", 0)),
    (Base() with { Bookings = new[] { Booking(100, -1, 550, "Ada") } },
        Error("BAD_BOOKING", 0)),
    (Base() with
    {
        Bookings = Enumerable.Range(0, 201)
            .Select(offset => Booking(500 + offset, 0, 1, "Ada")).ToArray()
    }, Error("BAD_BOOKING")),
    (Base() with
    {
        Bookings = new[] { Booking(100, 1, 1, "Ada") },
        PreferredDoctor = "Bo"
    }, Error("BAD_BOOKING", 0)),
    (Base() with { PreferredDoctor = "Bo" }, Error("UNKNOWN_DOCTOR")),
    (Base() with { PreferredDoctor = "Bo", RequestedDay = 109 },
        Error("UNKNOWN_DOCTOR")),
    (Base() with { RequestedDay = 99 }, Error("BAD_DAY_ORDER")),
    (Base() with { RequestedDay = 109 }, Error("BAD_DAY_ORDER")),
    (Base() with { RequestedDay = 99, PreferredDoctor = "Missing" },
        Error("UNKNOWN_DOCTOR")),
    (Base() with
    {
        Doctors = new[] { Doctor("Ada"), Doctor("ada") },
        Holidays = new[] { -1 }
    }, Error("BAD_DOCTORS", 1)),
    (Base() with
    {
        Holidays = new[] { -1 },
        Bookings = new[] { Booking(100, 540, 540, "Ada") }
    }, Error("BAD_HOLIDAY", 0)),
    (Base() with
    {
        RequestedDay = 99,
        Holidays = new[] { 100, 100 }
    }, Error("BAD_HOLIDAY", 1)),
    (Base() with { Doctors = new[] { Doctor("Ada", (1, 540, 1020)) } },
        Error("NO_SLOT")),
    (Base() with { Doctors = new[] { Doctor("Ada") } }, Error("NO_SLOT")),
    (Base() with { HorizonDays = 0, Holidays = new[] { 100 } }, Error("NO_SLOT")),
    (Base() with
    {
        HorizonDays = 0,
        Doctors = new[] { Doctor("Ada", (2, 540, 564)) }
    }, Error("NO_SLOT")),
    (Base() with
    {
        HorizonDays = 0,
        Doctors = new[] { Doctor("Ada", (2, 800, 900)) },
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Error("NO_SLOT")),
    (Base() with
    {
        PreferredDoctor = "Ada",
        Doctors = new[] { Doctor("Ada"), Doctor("Bo", (2, 540, 1020)) }
    }, Error("NO_SLOT")),
    (Base() with
    {
        HorizonDays = 0,
        Doctors = new[] { Doctor("Ada", (2, 540, 1020)) },
        Bookings = new[] { 540, 560, 580, 600 }
            .Select(start => Booking(100, start, start + 10, "Ada")).ToArray()
    }, Error("NO_SLOT")),
    (Base() with
    {
        NowDay = 999_992,
        RequestedDay = 1_000_000,
        HorizonDays = 14,
        Doctors = new[] { Doctor("Ada", (2, 540, 1020)) }
    }, Error("NO_SLOT")),
    (Base() with
    {
        NowDay = 999_999,
        RequestedDay = 1_000_000,
        HorizonDays = 14,
        Holidays = new[] { 1_000_000 }
    }, Error("NO_SLOT")),
};

foreach (var row in pinned)
{
    Check(row.Input, row.Expected);
    MatchOracle(row.Input);
}
foreach (var row in failures)
{
    Check(row.Input, row.Expected);
    MatchOracle(row.Input);
}

// A seeded splitmix64 stream keeps the random mix deterministic and well mixed.
ulong state = 20261017;
ulong Next()
{
    state += 0x9E3779B97F4A7C15UL;
    ulong value = state;
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9UL;
    value = (value ^ (value >> 27)) * 0x94D049BB133111EBUL;
    return value ^ (value >> 31);
}
int Below(int limit) => (int)((Next() >> 16) % (ulong)limit);
T Pick<T>(T[] values) => values[Below(values.Length)];

string Decorated(string name)
{
    string text = Below(2) == 0 ? name.ToLowerInvariant() : name.ToUpperInvariant();
    return Below(3) == 0 ? " " + text + " " : text;
}

string[] RandomNames() =>
    new[] { "Ada", "Bo", "Cy" }.Take(1 + Below(3)).ToArray();

(int Open, int Close) RandomSpan()
{
    int open = Pick(new[] { 540, 555, 600, 690, 780 });
    int close = Pick(new[] { 660, 700, 840, 1020 });
    return close > open ? (open, close) : (open, 1020);
}

Solution.Doctor RandomDoctor(string name)
{
    (int Open, int Close) span = RandomSpan();
    var weekdays = new List<int>();
    for (int weekday = 0; weekday < 7; weekday++)
    {
        if (Below(4) != 0) weekdays.Add(weekday);
    }
    if (!weekdays.Any(weekday => weekday < 6)) weekdays.Add(Below(6));
    weekdays.Sort();
    return Doctor(Decorated(name),
        weekdays.Select(weekday => (weekday, span.Open, span.Close)).ToArray());
}

Solution.Booking[] RandomBookings(string[] names, int requested, int last)
{
    var rows = new List<Solution.Booking>();
    int groups = Below(5);
    for (int group = 0; group < groups; group++)
    {
        string owner = Decorated(Pick(names));
        int day = requested + Below(last - requested + 1);
        int start = 540 + 5 * Below(85);
        int links = 1 + Below(3);
        for (int link = 0; link < links; link++)
        {
            int end = Math.Min(start + Pick(new[] { 10, 20, 30, 60 }), 1440);
            if (start >= end) break;
            rows.Add(Booking(day, start, end, owner));
            start = end;
        }
    }
    return rows.ToArray();
}

int capped = 0;
int valid = 0;
int invalid = 0;
const int Total = 2000;
var kindsSeen = new SortedSet<string>(StringComparer.Ordinal);
var doctorsSeen = new SortedSet<string>(StringComparer.Ordinal);
var weekdaysSeen = new SortedSet<int>();
var startsSeen = new SortedSet<int>();
var daysSeen = new SortedSet<int>();
var errorsSeen = new SortedSet<string>(StringComparer.Ordinal);
bool urgentSeen = false;
bool calmSeen = false;
bool indexedErrorSeen = false;

Solution.Request MostlyValid()
{
    int nowDay = 20 + Below(880);
    int requested = nowDay + Below(9);
    int horizon = 1 + Below(14);
    int last = Math.Min(Math.Min(requested + horizon, requested + 14), 1_000_000);
    string[] names = RandomNames();
    var doctors = names.Select(RandomDoctor).ToArray();
    var rows = new List<Solution.Booking>(RandomBookings(names, requested, last));
    if (Below(8) == 0)
    {
        string owner = Decorated(Pick(names));
        int day = requested + Below(last - requested + 1);
        for (int minute = 0; minute < 4; minute++)
            rows.Add(Booking(day, minute, minute + 1, owner));
        capped++;
    }
    int[] holidays = Enumerable.Range(0, Below(4))
        .Select(offset => requested + Below(last - requested + 1))
        .Distinct().OrderBy(day => day).ToArray();
    string preferred = Below(3) == 0 ? "" : Decorated(Pick(names));
    return Base() with
    {
        NowDay = nowDay,
        NowMinute = Below(1440),
        RequestedDay = requested,
        HorizonDays = horizon,
        Kind = Pick(new[] { "checkup", "consultation", "procedure" }),
        Urgent = Below(2) == 0,
        PreferredDoctor = preferred,
        Holidays = holidays,
        Doctors = doctors,
        Bookings = rows.ToArray()
    };
}

Solution.Request InvalidRequest()
{
    string[] names = RandomNames();
    var doctors = names.Select(RandomDoctor).ToArray();
    int nowDay = 20 + Below(880);
    Solution.Request request = Base() with
    {
        NowDay = nowDay,
        RequestedDay = nowDay + Below(3),
        Doctors = doctors
    };
    switch (Below(14))
    {
        case 0:
            return request with { NowDay = Pick(new[] { -1, 1_000_001 }) };
        case 1:
            return request with { NowMinute = Pick(new[] { -1, 1440, 5000 }) };
        case 2:
            return request with { HorizonDays = Pick(new[] { -1, 15, 30 }) };
        case 3:
            return request with { RequestedDay = Pick(new[] { -1, 1_000_001 }) };
        case 4:
            return request with { Kind = Pick(new[] { "", "other", "surgery", "check" }) };
        case 5:
            return request with { Doctors = Array.Empty<Solution.Doctor>() };
        case 6:
            return request with
            {
                Doctors = Enumerable.Range(0, 13)
                    .Select(number => Doctor($"D{number}", (2, 540, 1020))).ToArray()
            };
        case 7:
        {
            var rows = doctors.ToList();
            rows.Add(Doctor(Decorated(Pick(names)), (2, 540, 1020)));
            return request with { Doctors = rows.ToArray() };
        }
        case 8:
        {
            var rows = doctors.ToList();
            int index = Below(rows.Count);
            var windows = rows[index].Windows.ToList();
            windows.Add(Pick(new[]
            {
                new Solution.Window(7, 540, 600),
                new Solution.Window(-1, 540, 600),
                new Solution.Window(2, 540, 540),
                new Solution.Window(2, 540, 1441),
                new Solution.Window(2, -5, 600)
            }));
            rows[index] = new Solution.Doctor(rows[index].Name, windows.ToArray());
            return request with { Doctors = rows.ToArray() };
        }
        case 9:
            return Below(2) == 0
                ? request with { Holidays = Enumerable.Range(0, 61).ToArray() }
                : request with { Holidays = new[] { Pick(new[] { -1, 1_000_001 }) } };
        case 10:
        {
            string first = Pick(names);
            var rows = new List<Solution.Booking>
            {
                Booking(request.RequestedDay, 0, 1, first)
            };
            rows.Add(Pick(new[]
            {
                Booking(request.RequestedDay, 540, 540, first),
                Booking(request.RequestedDay, 540, 1441, first),
                Booking(-1, 540, 550, first),
                Booking(request.RequestedDay, 540, 550, "Missing"),
                Booking(request.RequestedDay, 540, 550, "bad@name")
            }));
            return request with { Bookings = rows.ToArray() };
        }
        case 11:
            return request with
            {
                Bookings = Enumerable.Range(0, 201)
                    .Select(offset => Booking(500 + offset, 0, 1, names[0])).ToArray()
            };
        case 12:
            if (Below(3) == 0)
                return request with
                {
                    PreferredDoctor = "Missing",
                    RequestedDay = request.NowDay + Pick(new[] { 9, 12 })
                };
            if (Below(2) == 0) return request with { PreferredDoctor = "Missing" };
            return request with { RequestedDay = request.NowDay + Pick(new[] { 9, 12 }) };
        default:
            return request with { Doctors = new[] { Doctor(Pick(names), (6, 540, 1020)) } };
    }
}

for (int round = 0; round < Total; round++)
{
    Solution.Request given = Below(8) == 0 ? InvalidRequest() : MostlyValid();
    Solution.Outcome want = Oracle(given);
    Check(given, want);
    if (want is Solution.Appointment slot)
    {
        valid++;
        kindsSeen.Add(given.Kind.Trim(' ').ToLowerInvariant());
        doctorsSeen.Add(slot.Doctor);
        weekdaysSeen.Add(slot.Day % 7);
        startsSeen.Add(slot.Start);
        daysSeen.Add(slot.Day);
        if (given.Urgent) urgentSeen = true;
        else calmSeen = true;
    }
    else
    {
        invalid++;
        var failure = (Solution.ClinicError)want;
        errorsSeen.Add(failure.Error);
        if (failure.Index is > 0) indexedErrorSeen = true;
    }
}

if (valid * 2 < Total)
    throw new InvalidOperationException($"valid request ratio below 50%: {valid}/{Total}");
if (invalid == 0) throw new InvalidOperationException("no invalid request was generated");
if (capped == 0) throw new InvalidOperationException("no forced daily cap was generated");
if (!urgentSeen || !calmSeen)
    throw new InvalidOperationException("urgent coverage missing from valid requests");
if (!indexedErrorSeen)
    throw new InvalidOperationException("no error carried a positive list index");
foreach (string value in new[] { "checkup", "consultation", "procedure" })
    if (!kindsSeen.Contains(value))
        throw new InvalidOperationException($"kind not covered: {value}");
foreach (string value in new[]
{
    "BAD_REQUEST", "BAD_DOCTORS", "BAD_WINDOW", "BAD_HOLIDAY", "BAD_BOOKING",
    "UNKNOWN_DOCTOR", "BAD_DAY_ORDER", "NO_SLOT"
})
    if (!errorsSeen.Contains(value))
        throw new InvalidOperationException($"error code not covered: {value}");
if (doctorsSeen.Count < 3) throw new InvalidOperationException("too few doctors scheduled");
if (weekdaysSeen.Count < 5) throw new InvalidOperationException("too few weekdays covered");
if (startsSeen.Count < 20) throw new InvalidOperationException("too few start minutes covered");
if (daysSeen.Count < 100) throw new InvalidOperationException("too few days covered");
Console.WriteLine(
    $"clinic-booking: {pinned.Length} worked and {failures.Length} error cases passed; "
    + $"{Total} seeded requests ({valid} scheduled, {invalid} rejected, {capped} forced caps); "
    + $"kinds [{string.Join(", ", kindsSeen)}], "
    + $"doctors [{string.Join(", ", doctorsSeen.Take(4))}] of {doctorsSeen.Count}, "
    + $"weekdays [{string.Join(", ", weekdaysSeen)}], starts {startsSeen.Count}, "
    + $"days {daysSeen.Count}, errors [{string.Join(", ", errorsSeen)}]");
