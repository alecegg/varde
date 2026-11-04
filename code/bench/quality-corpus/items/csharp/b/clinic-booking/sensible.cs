using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

public static class Solution
{
    public abstract record Outcome;

    public sealed record Window(int Weekday, int Open, int Close);

    public sealed record Doctor(string Name, Window[] Windows);

    public sealed record Booking(int Day, int Start, int End, string Doctor);

    public sealed record Request(
        int NowDay,
        int NowMinute,
        int RequestedDay,
        int HorizonDays,
        string Kind,
        bool Urgent,
        string PreferredDoctor,
        int[] Holidays,
        Doctor[] Doctors,
        Booking[] Bookings);

    public sealed record Appointment(int Day, int Start, int End, string Doctor, string[] Trace)
        : Outcome;

    public sealed record ClinicError(string Error, int? Index) : Outcome;

    private const int LatestDay = 1_000_000;
    private const int LatestHorizon = 14;
    private const int DailyLimit = 4;
    private const int NoticeMinutes = 60;
    private const int LunchOpen = 720;
    private const int LunchClose = 780;

    private static readonly System.Text.RegularExpressions.Regex NamePattern =
        new(@"\A[A-Za-z0-9 -]+\z", RegexOptions.CultureInvariant);

    /// <summary>
    /// Return the earliest valid appointment or the first validation error.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Request prepared = Normalize(request);
        Outcome? failure = Validate(prepared);
        if (failure is not null) return failure;
        (int Day, int Start, string Doctor, int End)? slot = FindSlot(prepared);
        return slot is null ? new ClinicError("NO_SLOT", null) : Assemble(slot.Value);
    }

    private static Request Normalize(Request request) => new(
        request.NowDay,
        request.NowMinute,
        request.RequestedDay,
        request.HorizonDays,
        request.Kind.Trim(' ').ToLowerInvariant(),
        request.Urgent,
        request.PreferredDoctor.Trim(' '),
        request.Holidays,
        request.Doctors
            .Select(doctor => new Doctor(doctor.Name.Trim(' '), doctor.Windows))
            .ToArray(),
        request.Bookings
            .Select(row => new Booking(row.Day, row.Start, row.End, row.Doctor.Trim(' ')))
            .ToArray());

    private static Outcome? Validate(Request request)
    {
        if (!ScalarsFit(request)) return new ClinicError("BAD_REQUEST", null);
        Outcome? failure = DoctorFailure(request.Doctors);
        if (failure is not null) return failure;
        HashSet<string> keys = DoctorKeys(request.Doctors);
        failure = WindowFailure(request.Doctors)
            ?? HolidayFailure(request.Holidays)
            ?? BookingFailure(request.Bookings, keys);
        return failure ?? OrderFailure(request, keys);
    }

    private static bool ScalarsFit(Request request) =>
        request.NowDay is >= 0 and <= LatestDay
        && request.RequestedDay is >= 0 and <= LatestDay
        && request.NowMinute is >= 0 and <= 1439
        && request.HorizonDays is >= 0 and <= LatestHorizon
        && request.Kind is "checkup" or "consultation" or "procedure";

    private static Outcome? DoctorFailure(Doctor[] doctors)
    {
        if (doctors.Length < 1 || doctors.Length > 12)
            return new ClinicError("BAD_DOCTORS", null);
        var seen = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
        for (int index = 0; index < doctors.Length; index++)
        {
            string? key = NameKey(doctors[index].Name);
            if (key is null || !seen.Add(key)) return new ClinicError("BAD_DOCTORS", index);
        }
        return null;
    }

    private static HashSet<string> DoctorKeys(Doctor[] doctors)
    {
        var keys = new HashSet<string>(StringComparer.Ordinal);
        foreach (Doctor doctor in doctors) keys.Add(NameKey(doctor.Name)!);
        return keys;
    }

    private static Outcome? WindowFailure(Doctor[] doctors)
    {
        for (int index = 0; index < doctors.Length; index++)
        {
            Window[] windows = doctors[index].Windows;
            if (windows.Length > 8) return new ClinicError("BAD_WINDOW", index);
            foreach (Window window in windows)
            {
                bool weekdayFits = window.Weekday is >= 0 and <= 6;
                bool spanFits = window.Open >= 0 && window.Open < window.Close
                    && window.Close <= 1440;
                if (!weekdayFits || !spanFits) return new ClinicError("BAD_WINDOW", index);
            }
        }
        return null;
    }

    private static Outcome? HolidayFailure(int[] holidays)
    {
        if (holidays.Length > 60) return new ClinicError("BAD_HOLIDAY", null);
        var seen = new HashSet<int>();
        for (int index = 0; index < holidays.Length; index++)
        {
            int day = holidays[index];
            if (day < 0 || day > LatestDay || !seen.Add(day))
                return new ClinicError("BAD_HOLIDAY", index);
        }
        return null;
    }

    private static Outcome? BookingFailure(Booking[] bookings, HashSet<string> keys)
    {
        if (bookings.Length > 200) return new ClinicError("BAD_BOOKING", null);
        for (int index = 0; index < bookings.Length; index++)
        {
            Booking booking = bookings[index];
            bool dayFits = booking.Day >= 0 && booking.Day <= LatestDay;
            bool spanFits = booking.Start >= 0 && booking.Start < booking.End
                && booking.End <= 1440;
            string? key = NameKey(booking.Doctor);
            if (!dayFits || !spanFits || key is null || !keys.Contains(key))
                return new ClinicError("BAD_BOOKING", index);
        }
        return null;
    }

    private static Outcome? OrderFailure(Request request, HashSet<string> keys)
    {
        string preferred = request.PreferredDoctor;
        bool unknown = preferred.Length > 0 && !keys.Contains(NameKey(preferred)!);
        if (unknown) return new ClinicError("UNKNOWN_DOCTOR", null);
        bool dayBeforeNow = request.RequestedDay < request.NowDay;
        bool dayTooLate = request.RequestedDay - request.NowDay > 8;
        if (dayBeforeNow || dayTooLate) return new ClinicError("BAD_DAY_ORDER", null);
        return null;
    }

    private static string? NameKey(string name)
    {
        if (name.Length == 0 || !NamePattern.IsMatch(name)) return null;
        return name.ToLowerInvariant();
    }

    private sealed record Scan(
        Request Request,
        int Duration,
        int Buffer,
        string PreferredKey,
        string?[] BookingKeys);

    private sealed record Slot(int Day, int Start, string Key, string Doctor, int End);

    private static (int Day, int Start, string Doctor, int End)? FindSlot(Request request)
    {
        (int Duration, int Buffer) = KindTiming(request.Kind);
        var scan = new Scan(
            request,
            Duration,
            Buffer,
            NameKey(request.PreferredDoctor) ?? "",
            System.Linq.Enumerable.ToArray(
                System.Linq.Enumerable.Select(request.Bookings, row => NameKey(row.Doctor))));
        var matches = new List<Slot>();
        foreach (int day in CandidateDays(request)) DayMatches(scan, day, matches);
        return EarliestSlot(matches);
    }

    private static (int Day, int Start, string Doctor, int End)? EarliestSlot(List<Slot> matches)
    {
        if (matches.Count == 0) return null;
        var first = matches
            .OrderBy(match => match.Day)
            .ThenBy(match => match.Start)
            .ThenBy(match => match.Key, StringComparer.Ordinal)
            .First();
        return (first.Day, first.Start, first.Doctor, first.End);
    }

    private static void DayMatches(Scan scan, int day, List<Slot> matches)
    {
        foreach (Doctor doctor in scan.Request.Doctors)
        {
            string key = NameKey(doctor.Name)!;
            if (PreferredMissed(scan.Request, scan.PreferredKey, key)) continue;
            for (int start = 0; start <= 1435; start += 5)
            {
                int end = start + scan.Duration;
                int reservedEnd = end + scan.Buffer;
                if (!FitsHours(doctor, day % 7, start, reservedEnd)) continue;
                if (!ScheduleAllows(scan, day, key, start, reservedEnd)) continue;
                matches.Add(new Slot(day, start, key, doctor.Name, end));
            }
        }
    }

    private static bool PreferredMissed(Request request, string preferredKey, string key) =>
        !request.Urgent && preferredKey.Length > 0 && key != preferredKey;

    private static bool FitsHours(Doctor doctor, int weekday, int start, int reservedEnd)
    {
        (int Open, int Close) opening = weekday switch
        {
            < 5 => (540, 1020),
            5 => (600, 840),
            _ => (0, 0)
        };
        if (start < opening.Open || reservedEnd > opening.Close) return false;
        if (start < LunchClose && reservedEnd > LunchOpen) return false;
        foreach (Window window in doctor.Windows)
        {
            if (window.Weekday != weekday) continue;
            if (window.Open <= start && reservedEnd <= window.Close) return true;
        }
        return false;
    }

    private static bool ScheduleAllows(
        Scan scan,
        int day,
        string key,
        int start,
        int reservedEnd)
    {
        Request request = scan.Request;
        if (day == request.NowDay && start < request.NowMinute + NoticeMinutes) return false;
        int taken = 0;
        for (int index = 0; index < scan.BookingKeys.Length; index++)
        {
            if (scan.BookingKeys[index] != key) continue;
            Booking booking = request.Bookings[index];
            if (booking.Day != day) continue;
            taken++;
            if (start < booking.End && booking.Start < reservedEnd) return false;
        }
        return taken < DailyLimit;
    }

    private static int[] CandidateDays(Request request)
    {
        int last = Math.Min(
            request.RequestedDay + LatestHorizon,
            Math.Min(request.RequestedDay + request.HorizonDays, LatestDay));
        var closed = new HashSet<int>(request.Holidays);
        var days = new List<int>();
        for (int day = request.RequestedDay; day <= last; day++)
        {
            if (!closed.Contains(day)) days.Add(day);
        }
        return days.ToArray();
    }

    private static (int Duration, int Buffer) KindTiming(string kind) => kind switch
    {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15)
    };

    private static Appointment Assemble((int Day, int Start, string Doctor, int End) slot) => new(
        slot.Day,
        slot.Start,
        slot.End,
        slot.Doctor,
        [
            "normalised",
            "validated",
            "holiday-filter",
            "hours-and-lunch",
            "notice",
            "doctor-availability",
            "daily-cap",
            "booking-conflicts",
            "urgent-priority",
            "earliest-grid-slot"
        ]);
}
