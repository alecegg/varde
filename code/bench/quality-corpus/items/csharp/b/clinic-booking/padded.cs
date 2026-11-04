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

    private sealed record Draft(
        Request Source,
        string Kind,
        string Preferred,
        string? PreferredKey,
        Doctor[] Doctors,
        Booking[] Bookings,
        int Duration,
        int Buffer);

    private sealed record Slot(
        int Day, int Start, int End, int Reserved, string Key, string Doctor);

    private sealed record Plan(Draft Draft, List<string> Trace);

    private const int LatestDay = 1_000_000;
    private const int LatestHorizon = 14;
    private const int DailyLimit = 4;
    private const int NoticeMinutes = 60;
    private const int LunchOpen = 720;
    private const int LunchClose = 780;
    private const int GridPitch = 5;
    private const int LastStart = 1435;

    private static readonly System.Text.RegularExpressions.Regex NamePattern =
        new(@"\A[A-Za-z0-9 -]+\z", RegexOptions.CultureInvariant);

    private static readonly (int Open, int Close)[] Opening =
    [
        (540, 1020),
        (540, 1020),
        (540, 1020),
        (540, 1020),
        (540, 1020),
        (600, 840),
        (0, 0)
    ];

    /// <summary>
    /// Return the earliest valid appointment or the first validation error.
    /// </summary>
    public static Outcome solution(Request request)
    {
        var trace = new List<string>();
        Draft draft = Normalise(request);
        Note(trace, "normalised");
        ClinicError? failure = Gate(draft);
        if (failure is not null) return failure;
        Note(trace, "validated");
        List<Slot> slots = Collect(new Plan(draft, trace));
        Slot? slot = Best(slots, draft, trace);
        return slot is null ? new ClinicError("NO_SLOT", null) : Finish(slot, trace);
    }

    private static Draft Normalise(Request request)
    {
        string kind = request.Kind.Trim(' ').ToLowerInvariant();
        string preferred = request.PreferredDoctor.Trim(' ');
        (Doctor[] doctors, Booking[] bookings) = TrimRows(request);
        (int duration, int buffer) = kind switch
        {
            "checkup" => (20, 5),
            "consultation" => (30, 10),
            _ => (60, 15)
        };
        return new Draft(request, kind, preferred, NameKey(preferred), doctors, bookings,
            duration, buffer);
    }

    private static (Doctor[] Doctors, Booking[] Bookings) TrimRows(Request request)
    {
        Doctor[] doctors = request.Doctors
            .Select(row => new Doctor(row.Name.Trim(' '), row.Windows))
            .ToArray();
        Booking[] bookings = request.Bookings
            .Select(row => new Booking(row.Day, row.Start, row.End, row.Doctor.Trim(' ')))
            .ToArray();
        return (doctors, bookings);
    }

    private static ClinicError? Gate(Draft draft) =>
        ShapeFits(draft)
        ?? DoctorsFit(draft)
        ?? WindowsFit(draft)
        ?? HolidaysFit(draft)
        ?? BookingsFit(draft)
        ?? OrderFits(draft);

    private static ClinicError? ShapeFits(Draft draft)
    {
        Request request = draft.Source;
        bool scalarsFit = request.NowDay is >= 0 and <= LatestDay
            && request.RequestedDay is >= 0 and <= LatestDay
            && request.NowMinute is >= 0 and <= 1439
            && request.HorizonDays is >= 0 and <= LatestHorizon
            && draft.Kind is "checkup" or "consultation" or "procedure";
        return scalarsFit ? null : new ClinicError("BAD_REQUEST", null);
    }

    private static ClinicError? DoctorsFit(Draft draft)
    {
        Doctor[] doctors = draft.Doctors;
        if (doctors.Length < 1 || doctors.Length > 12)
            return new ClinicError("BAD_DOCTORS", null);
        var keys = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
        for (int index = 0; index < doctors.Length; index++)
        {
            string? key = NameKey(doctors[index].Name);
            if (key is null || !keys.Add(key)) return new ClinicError("BAD_DOCTORS", index);
        }
        return null;
    }

    private static ClinicError? WindowsFit(Draft draft)
    {
        for (int index = 0; index < draft.Doctors.Length; index++)
        {
            Window[] windows = draft.Doctors[index].Windows;
            bool tooMany = windows.Length > 8;
            bool unfit = windows.Any(window => window.Weekday is < 0 or > 6
                || window.Open < 0 || window.Open >= window.Close || window.Close > 1440);
            if (tooMany || unfit) return new ClinicError("BAD_WINDOW", index);
        }
        return null;
    }

    private static ClinicError? HolidaysFit(Draft draft)
    {
        int[] holidays = draft.Source.Holidays;
        if (holidays.Length > 60) return new ClinicError("BAD_HOLIDAY", null);
        var seen = new HashSet<int>();
        for (int index = 0; index < holidays.Length; index++)
        {
            int day = holidays[index];
            bool dayFits = day >= 0 && day <= LatestDay;
            if (!dayFits || !seen.Add(day)) return new ClinicError("BAD_HOLIDAY", index);
        }
        return null;
    }

    private static ClinicError? BookingsFit(Draft draft)
    {
        Booking[] bookings = draft.Bookings;
        if (bookings.Length > 200) return new ClinicError("BAD_BOOKING", null);
        var known = KnownKeys(draft);
        int rotten = Array.FindIndex(bookings, row =>
            row.Day is < 0 or > LatestDay
            || row.Start < 0 || row.Start >= row.End || row.End > 1440
            || !known.Contains(NameKey(row.Doctor) ?? ""));
        return rotten < 0 ? null : new ClinicError("BAD_BOOKING", rotten);
    }

    private static ClinicError? OrderFits(Draft draft)
    {
        if (draft.Preferred.Length > 0 && !KnownKeys(draft).Contains(draft.PreferredKey ?? ""))
            return new ClinicError("UNKNOWN_DOCTOR", null);
        int gap = draft.Source.RequestedDay - draft.Source.NowDay;
        if (gap < 0 || gap > 8) return new ClinicError("BAD_DAY_ORDER", null);
        return null;
    }

    private static HashSet<string> KnownKeys(Draft draft) => new(
        draft.Doctors.Select(doctor => NameKey(doctor.Name)!),
        StringComparer.Ordinal);

    private static string? NameKey(string name)
    {
        if (name.Length == 0 || !NamePattern.IsMatch(name)) return null;
        return name.ToLowerInvariant();
    }

    private static List<Slot> Collect(Plan plan)
    {
        var slots = new List<Slot>();
        foreach (int day in Days(plan))
        {
            foreach (Doctor doctor in plan.Draft.Doctors)
            {
                string key = NameKey(doctor.Name)!;
                for (int start = 0; start <= LastStart; start += GridPitch)
                {
                    Offer(plan, doctor, key, day, start, slots);
                }
            }
        }
        return slots;
    }

    private static int[] Days(Plan plan)
    {
        Request request = plan.Draft.Source;
        var closed = new HashSet<int>(request.Holidays);
        int last = Math.Min(request.RequestedDay + LatestHorizon,
            Math.Min(request.RequestedDay + request.HorizonDays, LatestDay));
        Note(plan.Trace, "holiday-filter");
        return System.Linq.Enumerable.Range(request.RequestedDay, last - request.RequestedDay + 1)
            .Where(day => !closed.Contains(day))
            .ToArray();
    }

    private static void Offer(Plan plan, Doctor doctor, string key, int day, int start,
        List<Slot> slots)
    {
        int end = start + plan.Draft.Duration;
        var slot = new Slot(day, start, end, end + plan.Draft.Buffer, key, doctor.Name);
        if (!HoursHold(plan, slot)) return;
        if (!NoticeKept(plan, slot)) return;
        if (!WindowOpen(plan, doctor, slot)) return;
        if (!DiaryClear(plan, slot)) return;
        slots.Add(slot);
    }

    private static bool HoursHold(Plan plan, Slot slot)
    {
        (int open, int close) = Opening[slot.Day % 7];
        if (slot.Start < open || slot.Reserved > close) return false;
        if (slot.Start < LunchClose && slot.Reserved > LunchOpen) return false;
        Note(plan.Trace, "hours-and-lunch");
        return true;
    }

    private static bool NoticeKept(Plan plan, Slot slot)
    {
        Request request = plan.Draft.Source;
        bool sameDay = slot.Day == request.NowDay;
        if (sameDay && slot.Start < request.NowMinute + NoticeMinutes) return false;
        Note(plan.Trace, "notice");
        return true;
    }

    private static bool WindowOpen(Plan plan, Doctor doctor, Slot slot)
    {
        int weekday = slot.Day % 7;
        bool covered = doctor.Windows.Any(window => window.Weekday == weekday
            && window.Open <= slot.Start && slot.Reserved <= window.Close);
        if (!covered) return false;
        Note(plan.Trace, "doctor-availability");
        return true;
    }

    private static bool DiaryClear(Plan plan, Slot slot)
    {
        Booking[] same = plan.Draft.Bookings
            .Where(row => row.Day == slot.Day && NameKey(row.Doctor) == slot.Key)
            .ToArray();
        if (same.Length >= DailyLimit) return false;
        Note(plan.Trace, "daily-cap");
        if (same.Any(row => slot.Start < row.End && row.Start < slot.Reserved)) return false;
        Note(plan.Trace, "booking-conflicts");
        return true;
    }

    private static Slot? Best(List<Slot> slots, Draft draft, List<string> trace)
    {
        string? wanted = draft.Source.Urgent ? null : draft.PreferredKey;
        Note(trace, "urgent-priority");
        Note(trace, "earliest-grid-slot");
        return slots
            .Where(slot => wanted is null || slot.Key == wanted)
            .OrderBy(slot => slot.Day)
            .ThenBy(slot => slot.Start)
            .ThenBy(slot => slot.Key, StringComparer.Ordinal)
            .FirstOrDefault();
    }

    private static Appointment Finish(Slot slot, List<string> trace) => new(
        slot.Day,
        slot.Start,
        slot.End,
        slot.Doctor,
        trace.ToArray());

    private static void Note(List<string> trace, string label)
    {
        if (trace.Contains(label)) return;
        trace.Add(label);
    }
}
