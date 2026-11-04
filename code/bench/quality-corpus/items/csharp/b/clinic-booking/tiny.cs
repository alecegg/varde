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
        Scan scan = Prep(request);
        ClinicError? issue = Checks(scan);
        if (issue is not null) return issue;
        Slot? slot = Plan(scan);
        return slot is null ? new ClinicError("NO_SLOT", null) : Pack(slot);
    }

    private static Scan Prep(Request req)
    {
        Request clean = Clean(req);
        (int duration, int buffer) = Timing(clean.Kind);
        return new Scan(clean, Key(clean.PreferredDoctor) ?? "", duration, buffer,
            KeysOf(clean.Bookings));
    }

    private static Request Clean(Request req) => req with
    {
        Kind = Kd(req.Kind),
        PreferredDoctor = Nm(req.PreferredDoctor),
        Doctors = Docs(req.Doctors),
        Bookings = Bks(req.Bookings)
    };

    private static string Kd(string s) => s.Trim(' ').ToLowerInvariant();

    private static string Nm(string s) => s.Trim(' ');

    private static Doctor[] Docs(Doctor[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, Doc));

    private static Doctor Doc(Doctor row) => new(Nm(row.Name), row.Windows);

    private static Booking[] Bks(Booking[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, Bk));

    private static Booking Bk(Booking row) => new(row.Day, row.Start, row.End, Nm(row.Doctor));

    private static string? Key(string name) =>
        name.Length == 0 || !Pat.IsMatch(name) ? null : name.ToLowerInvariant();

    private static string?[] KeysOf(Booking[] rows) =>
        L.Enumerable.ToArray(L.Enumerable.Select(rows, row => Key(row.Doctor)));

    private static (int Duration, int Buffer) Timing(string kind) => kind switch
    {
        "checkup" => (20, 5),
        "consultation" => (30, 10),
        _ => (60, 15)
    };

    private static ClinicError? Checks(Scan scan) =>
        Scalars(scan) ?? DocsBad(scan) ?? WinBad(scan) ?? HolBad(scan)
        ?? BookBad(scan) ?? OrdBad(scan);

    private static ClinicError? Scalars(Scan scan) =>
        Ranges(scan) && KindOk(scan.Req.Kind) ? null : new ClinicError("BAD_REQUEST", null);

    private static bool Ranges(Scan scan) =>
        InRange(scan.Req.NowDay, 0, MaxDay)
        && InRange(scan.Req.RequestedDay, 0, MaxDay)
        && InRange(scan.Req.NowMinute, 0, 1439)
        && InRange(scan.Req.HorizonDays, 0, MaxHorizon);

    private static bool InRange(int value, int low, int high) => low <= value && value <= high;

    private static bool KindOk(string kind) => kind is "checkup" or "consultation" or "procedure";

    private static ClinicError? DocsBad(Scan scan) => Unique(scan.Req.Doctors);

    private static ClinicError? Unique(Doctor[] rows) =>
        rows.Length is < 1 or > 12 ? new ClinicError("BAD_DOCTORS", null) : Dups(rows);

    private static ClinicError? Dups(Doctor[] rows)
    {
        var seen = new G.HashSet<string>(S.StringComparer.Ordinal);
        for (int index = 0; index < rows.Length; index++)
            if (!Fresh(seen, rows[index].Name)) return new ClinicError("BAD_DOCTORS", index);
        return null;
    }

    private static bool Fresh(G.HashSet<string> seen, string name)
    {
        string? key = Key(name);
        return key is not null && seen.Add(key);
    }

    private static ClinicError? WinBad(Scan scan) => WinScan(scan.Req.Doctors);

    private static ClinicError? WinScan(Doctor[] rows)
    {
        for (int index = 0; index < rows.Length; index++)
        {
            if (!WinsOk(rows[index].Windows)) return new ClinicError("BAD_WINDOW", index);
        }
        return null;
    }

    private static bool WinsOk(Window[] rows) => rows.Length <= 8 && L.Enumerable.All(rows, WinOk);

    private static bool WinOk(Window row) =>
        row.Weekday is >= 0 and <= 6 && row.Open >= 0 && row.Open < row.Close
        && row.Close <= 1440;

    private static ClinicError? HolBad(Scan scan) => HolScan(scan.Req.Holidays);

    private static ClinicError? HolScan(int[] rows) =>
        rows.Length > 60 ? new ClinicError("BAD_HOLIDAY", null) : HolUnique(rows);

    private static ClinicError? HolUnique(int[] rows)
    {
        var seen = new G.HashSet<int>();
        for (int index = 0; index < rows.Length; index++)
            if (!FreshDay(seen, rows[index])) return new ClinicError("BAD_HOLIDAY", index);
        return null;
    }

    private static bool FreshDay(G.HashSet<int> seen, int day) =>
        InRange(day, 0, MaxDay) && seen.Add(day);

    private static ClinicError? BookBad(Scan scan) => BookRows(scan, scan.Req.Bookings);

    private static ClinicError? BookRows(Scan scan, Booking[] rows) =>
        rows.Length > 200 ? new ClinicError("BAD_BOOKING", null)
        : BookEach(rows, DocKeys(scan.Req.Doctors));

    private static ClinicError? BookEach(Booking[] rows, G.HashSet<string> keys)
    {
        for (int index = 0; index < rows.Length; index++)
        {
            if (!BookOk(rows[index], keys)) return new ClinicError("BAD_BOOKING", index);
        }
        return null;
    }

    private static bool BookOk(Booking row, G.HashSet<string> keys)
    {
        string? key = Key(row.Doctor);
        return InRange(row.Day, 0, MaxDay) && SpanOk(row.Start, row.End)
            && key is not null && keys.Contains(key);
    }

    private static bool SpanOk(int start, int end) => 0 <= start && start < end && end <= 1440;

    private static G.HashSet<string> DocKeys(Doctor[] rows)
    {
        var keys = new G.HashSet<string>(S.StringComparer.Ordinal);
        foreach (Doctor row in rows) keys.Add(Key(row.Name)!);
        return keys;
    }

    private static ClinicError? OrdBad(Scan scan) => PrefBad(scan) ?? DayBad(scan);

    private static ClinicError? PrefBad(Scan scan) =>
        PrefOk(scan) ? null : new ClinicError("UNKNOWN_DOCTOR", null);

    private static bool PrefOk(Scan scan) =>
        scan.Req.PreferredDoctor.Length == 0
        || DocKeys(scan.Req.Doctors).Contains(scan.PreferredKey);

    private static ClinicError? DayBad(Scan scan) =>
        DayOk(scan.Req) ? null : new ClinicError("BAD_DAY_ORDER", null);

    private static bool DayOk(Request req) =>
        req.NowDay <= req.RequestedDay && req.RequestedDay <= req.NowDay + 8;

    private static Slot? Plan(Scan scan)
    {
        Doctor[] doctors = Eligible(scan);
        var slots = new G.List<Slot>();
        foreach (int day in Days(scan)) AddDay(scan, doctors, day, slots);
        return Earliest(slots);
    }

    private static void AddDay(Scan scan, Doctor[] doctors, int day, G.List<Slot> slots)
    {
        foreach (Doctor doctor in doctors) Fill(scan, doctor, day, slots);
    }

    private static void Fill(Scan scan, Doctor doctor, int day, G.List<Slot> slots)
    {
        string key = Key(doctor.Name)!;
        for (int start = 0; start <= 1435; start += 5)
        {
            if (!Allowed(scan, doctor, day, start, key)) continue;
            slots.Add(SlotOf(scan, day, start, key, doctor));
        }
    }

    private static bool Allowed(Scan scan, Doctor doctor, int day, int start, string key)
    {
        int reserved = start + scan.Duration + scan.Buffer;
        return Hours(doctor, day % 7, start, reserved) && Notice(scan, day, start)
            && Cap(scan, day, key) && Clear(scan, day, key, start, reserved);
    }

    private static bool Hours(Doctor doctor, int weekday, int start, int end) =>
        Open(weekday, start, end) && !Lunch(start, end) && Hits(doctor, weekday, start, end);

    private static bool Open(int weekday, int start, int end)
    {
        (int low, int high) = weekday < 5 ? (540, 1020) : weekday == 5 ? (600, 840) : (0, 0);
        return low <= start && end <= high;
    }

    private static bool Lunch(int start, int end) => start < LunchHigh && end > LunchLow;

    private static bool Hits(Doctor doctor, int weekday, int start, int end) =>
        L.Enumerable.Any(doctor.Windows,
            row => row.Weekday == weekday && row.Open <= start && end <= row.Close);

    private static bool Notice(Scan scan, int day, int start) =>
        day != scan.Req.NowDay || start >= scan.Req.NowMinute + NoticeSpan;

    private static bool Cap(Scan scan, int day, string key) =>
        SameDay(scan, day, key).Length < DailyCap;

    private static bool Clear(Scan scan, int day, string key, int start, int end) =>
        !L.Enumerable.Any(SameDay(scan, day, key), row => start < row.End && row.Start < end);

    private static Booking[] SameDay(Scan scan, int day, string key) =>
        L.Enumerable.ToArray(L.Enumerable.Where(scan.Req.Bookings,
            (row, index) => scan.BookingKeys[index] == key && row.Day == day));

    private static int[] Days(Scan scan)
    {
        int last = Last(scan);
        var days = new G.List<int>();
        for (int day = scan.Req.RequestedDay; day <= last; day++) days.Add(day);
        return OpenDays(days, scan.Req.Holidays);
    }

    private static int Last(Scan scan) =>
        S.Math.Min(scan.Req.RequestedDay + MaxHorizon,
            S.Math.Min(scan.Req.RequestedDay + scan.Req.HorizonDays, MaxDay));

    private static int[] OpenDays(G.List<int> days, int[] closed)
    {
        var shut = new G.HashSet<int>(closed);
        days.RemoveAll(shut.Contains);
        return days.ToArray();
    }

    private static Doctor[] Eligible(Scan scan) =>
        L.Enumerable.ToArray(L.Enumerable.Where(scan.Req.Doctors, row => !Missed(scan, row)));

    private static bool Missed(Scan scan, Doctor row) =>
        !scan.Req.Urgent && scan.PreferredKey.Length > 0 && Key(row.Name) != scan.PreferredKey;

    private static Slot? Earliest(G.List<Slot> slots)
    {
        if (slots.Count == 0) return null;
        slots.Sort(Compare);
        return slots[0];
    }

    private static int Compare(Slot a, Slot b) =>
        a.Day != b.Day ? a.Day.CompareTo(b.Day)
        : a.Start != b.Start ? a.Start.CompareTo(b.Start)
        : S.StringComparer.Ordinal.Compare(a.Key, b.Key);

    private static Slot SlotOf(Scan scan, int day, int start, string key, Doctor doctor) =>
        new(day, start, key, doctor.Name, start + scan.Duration);

    private static Appointment Pack(Slot slot) =>
        new(slot.Day, slot.Start, slot.End, slot.Name, Trace());

    private static string[] Trace() => L.Enumerable.ToArray(Labels);
}
