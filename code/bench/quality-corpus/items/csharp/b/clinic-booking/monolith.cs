using System;
using System.Collections.Generic;
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
        bool urgentVisit = request.Urgent;
        string trimmedKind = request.Kind.Trim(' ');
        string kind = trimmedKind.ToLowerInvariant();
        string preferredDoctor = request.PreferredDoctor.Trim(' ');
        Doctor[] rawDoctors = request.Doctors;
        Doctor[] normalizedDoctors = new Doctor[rawDoctors.Length];
        for (int doctorIndex = 0; doctorIndex < rawDoctors.Length; doctorIndex++)
        {
            Doctor rawDoctor = rawDoctors[doctorIndex];
            string trimmedDoctorName = rawDoctor.Name.Trim(' ');
            normalizedDoctors[doctorIndex] = new Doctor(trimmedDoctorName, rawDoctor.Windows);
        }
        Booking[] rawBookings = request.Bookings;
        Booking[] normalizedBookings = new Booking[rawBookings.Length];
        for (int bookingIndex = 0; bookingIndex < rawBookings.Length; bookingIndex++)
        {
            Booking rawBooking = rawBookings[bookingIndex];
            string trimmedBookingDoctor = rawBooking.Doctor.Trim(' ');
            normalizedBookings[bookingIndex] = new Booking(
                rawBooking.Day, rawBooking.Start, rawBooking.End, trimmedBookingDoctor);
        }
        bool nowDayFits = nowDay >= 0 && nowDay <= 1_000_000;
        bool requestedDayFits = requestedDay >= 0 && requestedDay <= 1_000_000;
        bool nowMinuteFits = nowMinute >= 0 && nowMinute <= 1439;
        bool horizonFits = horizonDays >= 0 && horizonDays <= 14;
        bool scalarsFit = nowDayFits && requestedDayFits && nowMinuteFits && horizonFits;
        if (!scalarsFit) return new ClinicError("BAD_REQUEST", null);
        bool kindIsCheckup = kind == "checkup";
        bool kindIsConsultation = kind == "consultation";
        bool kindIsProcedure = kind == "procedure";
        bool knownKind = kindIsCheckup || kindIsConsultation || kindIsProcedure;
        if (!knownKind) return new ClinicError("BAD_REQUEST", null);
        int doctorCount = normalizedDoctors.Length;
        bool doctorCountTooSmall = doctorCount < 1;
        bool doctorCountTooLarge = doctorCount > 12;
        if (doctorCountTooSmall) return new ClinicError("BAD_DOCTORS", null);
        if (doctorCountTooLarge) return new ClinicError("BAD_DOCTORS", null);
        System.Collections.Generic.HashSet<string> doctorKeys =
            new System.Collections.Generic.HashSet<string>(System.StringComparer.Ordinal);
        for (int doctorIndex = 0; doctorIndex < doctorCount; doctorIndex++)
        {
            string doctorName = normalizedDoctors[doctorIndex].Name;
            bool doctorNameHasLength = doctorName.Length > 0;
            bool doctorNameFitsPattern = doctorNameHasLength && NamePattern.IsMatch(doctorName);
            if (!doctorNameFitsPattern) return new ClinicError("BAD_DOCTORS", doctorIndex);
            string doctorKey = doctorName.ToLowerInvariant();
            bool doctorKeyWasNew = doctorKeys.Add(doctorKey);
            if (!doctorKeyWasNew) return new ClinicError("BAD_DOCTORS", doctorIndex);
        }
        for (int doctorIndex = 0; doctorIndex < doctorCount; doctorIndex++)
        {
            Window[] windows = normalizedDoctors[doctorIndex].Windows;
            bool windowCountFits = windows.Length <= 8;
            if (!windowCountFits) return new ClinicError("BAD_WINDOW", doctorIndex);
            for (int windowIndex = 0; windowIndex < windows.Length; windowIndex++)
            {
                Window window = windows[windowIndex];
                int windowWeekday = window.Weekday;
                int windowOpen = window.Open;
                int windowClose = window.Close;
                bool weekdayFits = windowWeekday >= 0 && windowWeekday <= 6;
                bool openFits = windowOpen >= 0 && windowOpen < windowClose;
                bool closeFits = windowClose <= 1440;
                bool windowFits = weekdayFits && openFits && closeFits;
                if (!windowFits) return new ClinicError("BAD_WINDOW", doctorIndex);
            }
        }
        int[] holidays = request.Holidays;
        bool holidayCountFits = holidays.Length <= 60;
        if (!holidayCountFits) return new ClinicError("BAD_HOLIDAY", null);
        System.Collections.Generic.HashSet<int> closedDays =
            new System.Collections.Generic.HashSet<int>();
        for (int holidayIndex = 0; holidayIndex < holidays.Length; holidayIndex++)
        {
            int holidayDay = holidays[holidayIndex];
            bool holidayDayFits = holidayDay >= 0 && holidayDay <= 1_000_000;
            if (!holidayDayFits) return new ClinicError("BAD_HOLIDAY", holidayIndex);
            bool holidayDayWasNew = closedDays.Add(holidayDay);
            if (!holidayDayWasNew) return new ClinicError("BAD_HOLIDAY", holidayIndex);
        }
        bool bookingCountFits = normalizedBookings.Length <= 200;
        if (!bookingCountFits) return new ClinicError("BAD_BOOKING", null);
        var bookingKeys = new string[normalizedBookings.Length];
        for (int bookingIndex = 0; bookingIndex < normalizedBookings.Length; bookingIndex++)
        {
            Booking booking = normalizedBookings[bookingIndex];
            int bookingDay = booking.Day;
            int bookingStart = booking.Start;
            int bookingEnd = booking.End;
            bool bookingDayFits = bookingDay >= 0 && bookingDay <= 1_000_000;
            bool bookingStartFits = bookingStart >= 0 && bookingStart < bookingEnd;
            bool bookingEndFits = bookingEnd <= 1440;
            string bookingDoctorName = booking.Doctor;
            bool bookingDoctorFits = bookingDoctorName.Length > 0
                && NamePattern.IsMatch(bookingDoctorName);
            string? candidateBookingKey = bookingDoctorFits
                ? bookingDoctorName.ToLowerInvariant()
                : null;
            bool bookingDoctorKnown = candidateBookingKey is not null
                && doctorKeys.Contains(candidateBookingKey);
            bool bookingFits = bookingDayFits && bookingStartFits && bookingEndFits
                && bookingDoctorKnown;
            if (!bookingFits) return new ClinicError("BAD_BOOKING", bookingIndex);
            bookingKeys[bookingIndex] = candidateBookingKey!;
        }
        string preferredKey = "";
        bool preferredHasLength = preferredDoctor.Length > 0;
        if (preferredHasLength)
        {
            bool preferredFitsPattern = NamePattern.IsMatch(preferredDoctor);
            string? rawPreferredKey = preferredFitsPattern
                ? preferredDoctor.ToLowerInvariant()
                : null;
            bool preferredKnown = doctorKeys.Contains(rawPreferredKey!);
            if (!preferredKnown) return new ClinicError("UNKNOWN_DOCTOR", null);
            preferredKey = rawPreferredKey!;
        }
        bool dayBeforeNow = requestedDay < nowDay;
        bool dayTooLate = requestedDay - nowDay > 8;
        if (dayBeforeNow) return new ClinicError("BAD_DAY_ORDER", null);
        if (dayTooLate) return new ClinicError("BAD_DAY_ORDER", null);
        (int Duration, int Buffer) timing = kind switch
        {
            "checkup" => (20, 5),
            "consultation" => (30, 10),
            _ => (60, 15)
        };
        int duration = timing.Duration;
        int buffer = timing.Buffer;
        int lastCandidateDay = System.Math.Min(
            requestedDay + 14,
            System.Math.Min(requestedDay + horizonDays, 1_000_000));
        bool preferredIsSet = preferredKey.Length > 0;
        bool preferredFiltering = !urgentVisit && preferredIsSet;
        int noticeLimit = nowMinute + 60;
        System.Collections.Generic.List<int> candidateDays =
            new System.Collections.Generic.List<int>();
        for (int candidate = requestedDay; candidate <= lastCandidateDay; candidate++)
        {
            bool candidateIsClosed = closedDays.Contains(candidate);
            if (!candidateIsClosed) candidateDays.Add(candidate);
        }
        bool foundSlot = false;
        int bestDay = 0;
        int bestStart = 0;
        int bestEnd = 0;
        string bestKey = "";
        string bestDoctor = "";
        foreach (int day in candidateDays)
        {
            int weekday = day % 7;
            for (int doctorIndex = 0; doctorIndex < doctorCount; doctorIndex++)
            {
                Doctor doctor = normalizedDoctors[doctorIndex];
                string doctorName = doctor.Name;
                string doctorKey = doctorName.ToLowerInvariant();
                bool doctorIsPreferred = doctorKey == preferredKey;
                bool doctorIsSkipped = preferredFiltering && !doctorIsPreferred;
                if (doctorIsSkipped) continue;
                Window[] doctorWindows = doctor.Windows;
                for (int start = 0; start <= 1435; start += 5)
                {
                    int end = start + duration;
                    int reservedEnd = end + buffer;
                    (int Open, int Close) opening = weekday switch
                    {
                        < 5 => (540, 1020),
                        5 => (600, 840),
                        _ => (0, 0)
                    };
                    bool gridStartFits = start >= 0;
                    bool gridEndFits = start <= 1435;
                    bool afterOpening = start >= opening.Open;
                    bool beforeClosing = reservedEnd <= opening.Close;
                    bool insideOpening = gridStartFits && gridEndFits
                        && afterOpening && beforeClosing;
                    if (!insideOpening) continue;
                    bool touchesLunch = start < 780 && reservedEnd > 720;
                    if (touchesLunch) continue;
                    bool insideWindow = false;
                    foreach (Window window in doctorWindows)
                    {
                        bool otherWeekday = window.Weekday != weekday;
                        if (otherWeekday) continue;
                        bool windowOpensEarly = window.Open <= start;
                        bool windowClosesLate = reservedEnd <= window.Close;
                        bool windowCoversSlot = windowOpensEarly && windowClosesLate;
                        if (windowCoversSlot) insideWindow = true;
                    }
                    if (!insideWindow) continue;
                    bool sameDayAsNow = day == nowDay;
                    bool insideNotice = start < noticeLimit;
                    bool noticeBlocks = sameDayAsNow && insideNotice;
                    if (noticeBlocks) continue;
                    bool overlapFound = false;
                    int takenCount = 0;
                    for (int index = 0; index < bookingKeys.Length; index++)
                    {
                        string? bookingKey = bookingKeys[index];
                        bool keyMatches = bookingKey == doctorKey;
                        if (!keyMatches) continue;
                        Booking booking = normalizedBookings[index];
                        int bookedDay = booking.Day;
                        int bookedStart = booking.Start;
                        int bookedEnd = booking.End;
                        bool sameDay = bookedDay == day;
                        if (!sameDay) continue;
                        takenCount++;
                        bool startsEarly = start < bookedEnd;
                        bool endsLate = bookedStart < reservedEnd;
                        bool bookingOverlaps = startsEarly && endsLate;
                        if (bookingOverlaps)
                        {
                            overlapFound = true;
                            break;
                        }
                    }
                    if (overlapFound) continue;
                    bool dayIsFull = takenCount >= 4;
                    if (dayIsFull) continue;
                    bool earlierDay = foundSlot && day < bestDay;
                    bool sameDayEarlier = foundSlot && day == bestDay && start < bestStart;
                    bool sameStartEarlierKey = foundSlot && day == bestDay && start == bestStart
                        && System.String.CompareOrdinal(doctorKey, bestKey) < 0;
                    bool betterSlot = !foundSlot || earlierDay || sameDayEarlier
                        || sameStartEarlierKey;
                    if (betterSlot)
                    {
                        foundSlot = true;
                        bestDay = day;
                        bestStart = start;
                        bestEnd = end;
                        bestKey = doctorKey;
                        bestDoctor = doctorName;
                    }
                }
            }
        }
        if (!foundSlot) return new ClinicError("NO_SLOT", null);
        string[] trace = [
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
        ];
        return new Appointment(bestDay, bestStart, bestEnd, bestDoctor, trace);
    }
}
