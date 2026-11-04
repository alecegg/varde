using G = System.Collections.Generic;
using L = System.Linq;
using R = System.Text.RegularExpressions;
using S = System;

public static class Solution
{
    public abstract record Outcome;
    public sealed record Window(int Weekday, int Open, int Close);
    public sealed record Doctor(string Name, Window[] Windows);
    public sealed record Booking(int Day, int Start, int End, string Doctor);
    public sealed record Request(int NowDay, int NowMinute, int RequestedDay, int HorizonDays,
        string Kind, bool Urgent, string PreferredDoctor, int[] Holidays, Doctor[] Doctors,
        Booking[] Bookings);
    public sealed record Appointment(int Day, int Start, int End, string Doctor,
        string[] Trace) : Outcome;
    public sealed record ClinicError(string Error, int? Index) : Outcome;

    private sealed record Scan(
        Request Req, string PreferredKey, int Duration, int Buffer, string?[] BookingKeys);

    private sealed record Slot(int Day, int Start, string Key, string Name, int End);

    private const int MaxDay = 1_000_000;
    private const int MaxHorizon = 14;
    private const int DailyCap = 4;
    private const int NoticeSpan = 60;
    private const int LunchLow = 720;
    private const int LunchHigh = 780;

    private static readonly R.Regex Pat =
        new(@"\A[A-Za-z0-9 -]+\z", R.RegexOptions.CultureInvariant);

    private static readonly string[] Labels =
    [
        "normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
        "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
        "earliest-grid-slot"
    ];

    /// <summary>
    /// Return the earliest valid appointment or the first validation error.
    /// </summary>
    public static Outcome solution(Request request)
    {
        Scan scan = Normalize(request);
        ClinicError? issue = Validate(scan);
        if (issue is not null) return issue;
        Slot? slot = FindSlot(scan);
        return slot is null ? new ClinicError("NO_SLOT", null) : Assemble(slot);
    }

    private static Scan Normalize(Request req)
    {
        Request clean = TrimRequest(req);
        (int duration, int buffer) = KindTiming(clean.Kind);
        return new Scan(clean, NameKey(clean.PreferredDoctor) ?? "", duration, buffer,
            BookingKeys(clean.Bookings));
    }

    private static Request TrimRequest(Request req) => req with
    {
        Kind = CleanKind(req.Kind),
        PreferredDoctor = CleanName(req.PreferredDoctor),
        Doctors = CleanDoctors(req.Doctors),
        Bookings = CleanBookings(req.Bookings)
    };

    private static string CleanKind(string s) => s.Trim(' ').ToLowerInvariant();

    private static string CleanName(string s) => s.Trim(' ');

    private static Doctor[] CleanDoctors(Doctor[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, CleanDoctor));

    private static Doctor CleanDoctor(Doctor row) => new(CleanName(row.Name), row.Windows);

    private static Booking[] CleanBookings(Booking[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, CleanBooking));

    private static Booking CleanBooking(Booking row) =>
        new(row.Day, row.Start, row.End, CleanName(row.Doctor));

    private static string? NameKey(string name) =>
        name.Length == 0 || !Pat.IsMatch(name) ? null : name.ToLowerInvariant();

    private static string?[] BookingKeys(Booking[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, row => NameKey(row.Doctor)));

    private static (int Duration, int Buffer) KindTiming(string kind) => kind switch
    {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15)
    };

    private static ClinicError? Validate(Scan scan) =>
        ScalarFailure(scan) ?? DoctorFailure(scan) ?? WindowFailure(scan) ?? HolidayFailure(scan)
        ?? BookingFailure(scan) ?? OrderFailure(scan);

    private static ClinicError? ScalarFailure(Scan scan) =>
        BoundsFit(scan) && KnownKind(scan.Req.Kind) ? null : new ClinicError("BAD_REQUEST", null);

    private static bool BoundsFit(Scan scan) =>
        WithinBounds(scan.Req.NowDay, 0, MaxDay)
        && WithinBounds(scan.Req.RequestedDay, 0, MaxDay)
        && WithinBounds(scan.Req.NowMinute, 0, 1439)
        && WithinBounds(scan.Req.HorizonDays, 0, MaxHorizon);

    private static bool WithinBounds(int value, int low, int high) => low <= value && value <= high;

    private static bool KnownKind(string kind) =>
        kind is "checkup" or "consultation" or "procedure";

    private static ClinicError? DoctorFailure(Scan scan) => UniqueDoctors(scan.Req.Doctors);

    private static ClinicError? UniqueDoctors(Doctor[] rows) =>
        rows.Length is < 1 or > 12 ? new ClinicError("BAD_DOCTORS", null) : DuplicateDoctor(rows);

    private static ClinicError? DuplicateDoctor(Doctor[] rows)
    {
        var seen = new G.HashSet<string>(S.StringComparer.Ordinal);
        for (int index = 0; index < rows.Length; index++)
            if (!ClaimName(seen, rows[index].Name)) return new ClinicError("BAD_DOCTORS", index);
        return null;
    }

    private static bool ClaimName(G.HashSet<string> seen, string name)
    {
        string? key = NameKey(name);
        return key is not null && seen.Add(key);
    }

    private static ClinicError? WindowFailure(Scan scan) => ScanWindows(scan.Req.Doctors);

    private static ClinicError? ScanWindows(Doctor[] rows)
    {
        for (int index = 0; index < rows.Length; index++)
        {
            if (!WindowsAllFit(rows[index].Windows)) return new ClinicError("BAD_WINDOW", index);
        }
        return null;
    }

    private static bool WindowsAllFit(Window[] rows) =>
        rows.Length <= 8 && L.Enumerable.All(rows, WindowFits);

    private static bool WindowFits(Window row) =>
        row.Weekday is >= 0 and <= 6 && row.Open >= 0 && row.Open < row.Close
        && row.Close <= 1440;

    private static ClinicError? HolidayFailure(Scan scan) => ScanHolidays(scan.Req.Holidays);

    private static ClinicError? ScanHolidays(int[] rows) =>
        rows.Length > 60 ? new ClinicError("BAD_HOLIDAY", null) : DuplicateHoliday(rows);

    private static ClinicError? DuplicateHoliday(int[] rows)
    {
        var seen = new G.HashSet<int>();
        for (int index = 0; index < rows.Length; index++)
            if (!ClaimDay(seen, rows[index])) return new ClinicError("BAD_HOLIDAY", index);
        return null;
    }

    private static bool ClaimDay(G.HashSet<int> seen, int day) =>
        WithinBounds(day, 0, MaxDay) && seen.Add(day);

    private static ClinicError? BookingFailure(Scan scan) => BookingRows(scan, scan.Req.Bookings);

    private static ClinicError? BookingRows(Scan scan, Booking[] rows) =>
        rows.Length > 200 ? new ClinicError("BAD_BOOKING", null)
        : FirstBadBooking(rows, DoctorKeys(scan.Req.Doctors));

    private static ClinicError? FirstBadBooking(Booking[] rows, G.HashSet<string> keys)
    {
        for (int index = 0; index < rows.Length; index++)
        {
            if (!BookingFits(rows[index], keys)) return new ClinicError("BAD_BOOKING", index);
        }
        return null;
    }

    private static bool BookingFits(Booking row, G.HashSet<string> keys)
    {
        string? key = NameKey(row.Doctor);
        return WithinBounds(row.Day, 0, MaxDay) && SpanFits(row.Start, row.End)
            && key is not null && keys.Contains(key);
    }

    private static bool SpanFits(int start, int end) => 0 <= start && start < end && end <= 1440;

    private static G.HashSet<string> DoctorKeys(Doctor[] rows)
    {
        var keys = new G.HashSet<string>(S.StringComparer.Ordinal);
        foreach (Doctor row in rows) keys.Add(NameKey(row.Name)!);
        return keys;
    }

    private static ClinicError? OrderFailure(Scan scan) =>
        PreferredFailure(scan) ?? DayOrderFailure(scan);

    private static ClinicError? PreferredFailure(Scan scan) =>
        PreferredKnown(scan) ? null : new ClinicError("UNKNOWN_DOCTOR", null);

    private static bool PreferredKnown(Scan scan) =>
        scan.Req.PreferredDoctor.Length == 0
        || DoctorKeys(scan.Req.Doctors).Contains(scan.PreferredKey);

    private static ClinicError? DayOrderFailure(Scan scan) =>
        DayOrderFits(scan.Req) ? null : new ClinicError("BAD_DAY_ORDER", null);

    private static bool DayOrderFits(Request req) =>
        req.NowDay <= req.RequestedDay && req.RequestedDay <= req.NowDay + 8;

    private static Slot? FindSlot(Scan scan)
    {
        Doctor[] doctors = EligibleDoctors(scan);
        var slots = new G.List<Slot>();
        foreach (int day in CandidateDays(scan)) DayMatches(scan, doctors, day, slots);
        return EarliestSlot(slots);
    }

    private static void DayMatches(Scan scan, Doctor[] doctors, int day, G.List<Slot> slots)
    {
        foreach (Doctor doctor in doctors) DoctorStarts(scan, doctor, day, slots);
    }

    private static void DoctorStarts(Scan scan, Doctor doctor, int day, G.List<Slot> slots)
    {
        string key = NameKey(doctor.Name)!;
        for (int start = 0; start <= 1435; start += 5)
        {
            if (!SlotAllowed(scan, doctor, day, start, key)) continue;
            slots.Add(NewSlot(scan, day, start, key, doctor));
        }
    }

    private static bool SlotAllowed(Scan scan, Doctor doctor, int day, int start, string key)
    {
        int reserved = start + scan.Duration + scan.Buffer;
        return FitsHours(doctor, day % 7, start, reserved) && NoticeAllows(scan, day, start)
            && DailyCapAllows(scan, day, key) && BookingClear(scan, day, key, start, reserved);
    }

    private static bool FitsHours(Doctor doctor, int weekday, int start, int end) =>
        WithinOpening(weekday, start, end) && !LunchOverlap(start, end)
        && WindowMatches(doctor, weekday, start, end);

    private static bool WithinOpening(int weekday, int start, int end)
    {
        (int low, int high) = weekday < 5 ? (540, 1020) : weekday == 5 ? (600, 840) : (0, 0);
        return low <= start && end <= high;
    }

    private static bool LunchOverlap(int start, int end) => start < LunchHigh && end > LunchLow;

    private static bool WindowMatches(Doctor doctor, int weekday, int start, int end) =>
        L.Enumerable.Any(doctor.Windows,
            row => row.Weekday == weekday && row.Open <= start && end <= row.Close);

    private static bool NoticeAllows(Scan scan, int day, int start) =>
        day != scan.Req.NowDay || start >= scan.Req.NowMinute + NoticeSpan;

    private static bool DailyCapAllows(Scan scan, int day, string key) =>
        SameDayBookings(scan, day, key).Length < DailyCap;

    private static bool BookingClear(Scan scan, int day, string key, int start, int end) =>
        !L.Enumerable.Any(SameDayBookings(scan, day, key),
            row => start < row.End && row.Start < end);

    private static Booking[] SameDayBookings(Scan scan, int day, string key) =>
        L.Enumerable.ToArray(L.Enumerable.Where(scan.Req.Bookings,
            (row, index) => scan.BookingKeys[index] == key && row.Day == day));

    private static int[] CandidateDays(Scan scan)
    {
        int last = LastDay(scan);
        var days = new G.List<int>();
        for (int day = scan.Req.RequestedDay; day <= last; day++) days.Add(day);
        return WithoutHolidays(days, scan.Req.Holidays);
    }

    private static int LastDay(Scan scan) =>
        S.Math.Min(scan.Req.RequestedDay + MaxHorizon,
            S.Math.Min(scan.Req.RequestedDay + scan.Req.HorizonDays, MaxDay));

    private static int[] WithoutHolidays(G.List<int> days, int[] closed)
    {
        var shut = new G.HashSet<int>(closed);
        days.RemoveAll(shut.Contains);
        return days.ToArray();
    }

    private static Doctor[] EligibleDoctors(Scan scan) =>
        L.Enumerable.ToArray(
            L.Enumerable.Where(scan.Req.Doctors, row => !PreferredMissed(scan, row)));

    private static bool PreferredMissed(Scan scan, Doctor row) =>
        !scan.Req.Urgent && scan.PreferredKey.Length > 0 && NameKey(row.Name) != scan.PreferredKey;

    private static Slot? EarliestSlot(G.List<Slot> slots)
    {
        if (slots.Count == 0) return null;
        slots.Sort(SlotOrder);
        return slots[0];
    }

    private static int SlotOrder(Slot a, Slot b) =>
        a.Day != b.Day ? a.Day.CompareTo(b.Day)
        : a.Start != b.Start ? a.Start.CompareTo(b.Start)
        : S.StringComparer.Ordinal.Compare(a.Key, b.Key);

    private static Slot NewSlot(Scan scan, int day, int start, string key, Doctor doctor) =>
        new(day, start, key, doctor.Name, start + scan.Duration);

    private static Appointment Assemble(Slot slot) =>
        new(slot.Day, slot.Start, slot.End, slot.Name, TraceLabels());

    private static string[] TraceLabels() => L.Enumerable.ToArray(Labels);
}
