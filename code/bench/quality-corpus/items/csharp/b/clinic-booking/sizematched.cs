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

    private static readonly System.Text.RegularExpressions.Regex NamePattern =
        new(@"\A[A-Za-z0-9 -]+\z", RegexOptions.CultureInvariant);

    /// <summary>
    /// Return the earliest valid appointment or the first validation error.
    /// </summary>
    public static Outcome solution(Request request)
    {
        int nowDay = request.NowDay;
        int nowMinute = request.NowMinute;
        int requestedDay = request.RequestedDay;
        int horizonDays = request.HorizonDays;
        int dailyLimit = 4;
        int noticeMinutes = 60;
        string kind = request.Kind.Trim(' ').ToLowerInvariant();
        string preferredDoctor = request.PreferredDoctor.Trim(' ');

        var doctors = new Doctor[request.Doctors.Length];
        for (int index = 0; index < doctors.Length; index++)
        {
            Doctor doctor = request.Doctors[index];
            string trimmedName = doctor.Name.Trim(' ');
            doctors[index] = new Doctor(trimmedName, doctor.Windows);
        }
        var bookings = new Booking[request.Bookings.Length];
        for (int index = 0; index < bookings.Length; index++)
        {
            Booking booking = request.Bookings[index];
            string trimmedDoctor = booking.Doctor.Trim(' ');
            bookings[index] = new Booking(booking.Day, booking.Start, booking.End, trimmedDoctor);
        }

        bool nowDayInRange = nowDay >= 0 && nowDay <= 1_000_000;
        bool requestedDayInRange = requestedDay >= 0 && requestedDay <= 1_000_000;
        bool nowMinuteInRange = nowMinute >= 0 && nowMinute <= 1439;
        bool horizonInRange = horizonDays >= 0 && horizonDays <= 14;
        bool kindRecognised = kind is "checkup" or "consultation" or "procedure";
        bool requestFits = nowDayInRange && requestedDayInRange && nowMinuteInRange
            && horizonInRange && kindRecognised;
        if (!requestFits) return new ClinicError("BAD_REQUEST", null);

        bool doctorCountInRange = doctors.Length is >= 1 and <= 12;
        if (!doctorCountInRange) return new ClinicError("BAD_DOCTORS", null);
        var doctorKeys = new HashSet<string>(StringComparer.Ordinal);
        var doctorKeyList = new string[doctors.Length];
        for (int index = 0; index < doctors.Length; index++)
        {
            string name = doctors[index].Name;
            bool nameHasLength = name.Length > 0;
            bool nameMatchesPattern = nameHasLength && NamePattern.IsMatch(name);
            string key = nameMatchesPattern ? name.ToLowerInvariant() : "";
            bool keyIsNew = doctorKeys.Add(key);
            if (!nameMatchesPattern || !keyIsNew)
                return new ClinicError("BAD_DOCTORS", index);
            doctorKeyList[index] = key;
        }

        for (int index = 0; index < doctors.Length; index++)
        {
            Window[] windows = doctors[index].Windows;
            bool windowCountInRange = windows.Length <= 8;
            if (!windowCountInRange) return new ClinicError("BAD_WINDOW", index);
            foreach (Window window in windows)
            {
                int windowWeekday = window.Weekday;
                int windowOpen = window.Open;
                int windowClose = window.Close;
                bool weekdayInRange = windowWeekday >= 0 && windowWeekday <= 6;
                bool openInRange = windowOpen >= 0 && windowOpen < windowClose;
                bool closeInRange = windowClose <= 1440;
                bool windowFits = weekdayInRange && openInRange && closeInRange;
                if (!windowFits) return new ClinicError("BAD_WINDOW", index);
            }
        }

        int[] holidays = request.Holidays;
        bool holidayCountInRange = holidays.Length <= 60;
        if (!holidayCountInRange) return new ClinicError("BAD_HOLIDAY", null);
        var closedDays = new HashSet<int>();
        for (int index = 0; index < holidays.Length; index++)
        {
            int day = holidays[index];
            bool dayInRange = day >= 0 && day <= 1_000_000;
            bool dayIsNew = closedDays.Add(day);
            if (!dayInRange || !dayIsNew) return new ClinicError("BAD_HOLIDAY", index);
        }

        bool bookingCountInRange = bookings.Length <= 200;
        if (!bookingCountInRange) return new ClinicError("BAD_BOOKING", null);
        var bookingKeys = new string[bookings.Length];
        for (int index = 0; index < bookings.Length; index++)
        {
            Booking booking = bookings[index];
            int bookingDay = booking.Day;
            int bookingStart = booking.Start;
            int bookingEnd = booking.End;
            bool dayInRange = bookingDay >= 0 && bookingDay <= 1_000_000;
            bool startInRange = bookingStart >= 0 && bookingStart < bookingEnd;
            bool endInRange = bookingEnd <= 1440;
            string name = booking.Doctor;
            bool nameHasLength = name.Length > 0;
            bool nameMatchesPattern = nameHasLength && NamePattern.IsMatch(name);
            string key = nameMatchesPattern ? name.ToLowerInvariant() : "";
            bool doctorExists = doctorKeys.Contains(key);
            bool bookingFits = dayInRange && startInRange && endInRange
                && nameMatchesPattern && doctorExists;
            if (!bookingFits) return new ClinicError("BAD_BOOKING", index);
            bookingKeys[index] = key;
        }

        System.Collections.Generic.Dictionary<(string Key, int Day), List<Booking>>
            bookingsByDoctorDay = new();
        for (int index = 0; index < bookings.Length; index++)
        {
            Booking booking = bookings[index];
            var groupKey = (Key: bookingKeys[index], Day: booking.Day);
            if (!bookingsByDoctorDay.TryGetValue(groupKey, out List<Booking>? dayBookings))
            {
                dayBookings = new List<Booking>();
                bookingsByDoctorDay.Add(groupKey, dayBookings);
            }
            dayBookings.Add(booking);
        }

        string preferredKey = "";
        bool preferredPresent = preferredDoctor.Length > 0;
        if (preferredPresent)
        {
            bool preferredMatchesPattern = NamePattern.IsMatch(preferredDoctor);
            string? candidateKey = preferredMatchesPattern
                ? preferredDoctor.ToLowerInvariant()
                : null;
            bool preferredKnown = doctorKeys.Contains(candidateKey!);
            if (!preferredKnown) return new ClinicError("UNKNOWN_DOCTOR", null);
            preferredKey = candidateKey!;
        }
        bool dayBeforeNow = requestedDay < nowDay;
        bool dayTooLate = requestedDay - nowDay > 8;
        if (dayBeforeNow || dayTooLate) return new ClinicError("BAD_DAY_ORDER", null);

        (int Duration, int Buffer) timing = kind switch
        {
            "checkup" => (20, 5),
            "consultation" => (30, 10),
            _ => (60, 15)
        };
        int duration = timing.Duration;
        int buffer = timing.Buffer;
        int horizonLimit = 14;
        int lastDay = Math.Min(
            requestedDay + horizonLimit,
            Math.Min(requestedDay + horizonDays, 1_000_000));
        var openings = new Dictionary<int, (int Open, int Close)>();
        for (int weekday = 0; weekday <= 6; weekday++)
        {
            openings[weekday] = weekday switch
            {
                < 5 => (540, 1020),
                5 => (600, 840),
                _ => (0, 0)
            };
        }
        var candidateDays = new List<(int Day, int Weekday)>();
        for (int day = requestedDay; day <= lastDay; day++)
        {
            bool dayIsClosed = closedDays.Contains(day);
            if (!dayIsClosed) candidateDays.Add((day, day % 7));
        }

        bool urgentVisit = request.Urgent;
        bool preferredRequired = !urgentVisit && preferredKey.Length > 0;
        int noticeLimit = nowMinute + noticeMinutes;
        var matches = new List<(int Day, int Start, string Key, string Doctor, int End)>();
        foreach ((int day, int weekday) in candidateDays)
        {
            (int Open, int Close) opening = openings[weekday];
            for (int index = 0; index < doctors.Length; index++)
            {
                Doctor doctor = doctors[index];
                string key = doctorKeyList[index];
                bool otherDoctor = preferredRequired && key != preferredKey;
                if (otherDoctor) continue;
                Window[] doctorWindows = doctor.Windows;
                for (int start = 0; start <= 1435; start += 5)
                {
                    int end = start + duration;
                    int reservedEnd = end + buffer;
                    bool afterOpening = start >= opening.Open;
                    bool beforeClosing = reservedEnd <= opening.Close;
                    bool clearsLunch = start >= 780 || reservedEnd <= 720;
                    bool hoursFit = afterOpening && beforeClosing && clearsLunch;
                    if (!hoursFit) continue;
                    bool insideWindow = false;
                    foreach (Window window in doctorWindows)
                    {
                        bool windowWeekday = window.Weekday == weekday;
                        if (!windowWeekday) continue;
                        bool windowFits = window.Open <= start && reservedEnd <= window.Close;
                        if (windowFits) insideWindow = true;
                    }
                    if (!insideWindow) continue;
                    bool sameDayAsNow = day == nowDay;
                    bool afterNotice = !sameDayAsNow || start >= noticeLimit;
                    if (!afterNotice) continue;
                    var lookup = (Key: key, Day: day);
                    bool hasBookings = bookingsByDoctorDay.TryGetValue(
                        lookup, out List<Booking>? sameDay);
                    bool conflicts = false;
                    if (hasBookings)
                    {
                        foreach (Booking row in sameDay!)
                        {
                            bool startsEarly = start < row.End;
                            bool endsLate = row.Start < reservedEnd;
                            bool overlaps = startsEarly && endsLate;
                            if (overlaps) conflicts = true;
                        }
                    }
                    if (conflicts) continue;
                    bool dayIsFull = hasBookings && sameDay!.Count >= dailyLimit;
                    if (dayIsFull) continue;
                    matches.Add((day, start, key, doctor.Name, end));
                }
            }
        }
        bool anyMatch = System.Linq.Enumerable.Any(matches);
        if (!anyMatch) return new ClinicError("NO_SLOT", null);
        var earliest = matches
            .OrderBy(match => match.Day)
            .ThenBy(match => match.Start)
            .ThenBy(match => match.Key, StringComparer.Ordinal)
            .First();
        int slotDay = earliest.Day;
        int slotStart = earliest.Start;
        int slotEnd = earliest.End;
        string slotDoctor = earliest.Doctor;
        return new Appointment(
            slotDay,
            slotStart,
            slotEnd,
            slotDoctor,
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
}
