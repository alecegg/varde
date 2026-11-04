import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public class solution {
    record Request(long nowDay, long nowMinute, long requestedDay, long horizonDays, String kind,
            boolean urgent, String preferredDoctor, List<Long> holidays, List<Doctor> doctors,
            List<Booking> bookings) {}

    record Doctor(String name, List<Window> windows) {}

    record Window(long weekday, long open, long close) {}

    record Booking(long day, long start, long end, String doctor) {}

    record Appointment(long day, long start, long end, String doctor, List<String> trace) {}

    record ClinicError(String code, Integer index) {}

    record NormalDoctor(String name, String key, List<Window> windows) {}

    record NormalBooking(long day, long start, long end, String key) {}

    record Clinic(long nowDay, long nowMinute, long requestedDay, long horizonDays, String kind,
            boolean urgent, String preferredDoctor, String preferredKey, List<Long> holidays,
            List<NormalDoctor> doctors, List<NormalBooking> bookings) {}

    record Timing(long duration, long buffer) {}

    record Slot(long day, long start, long end, String doctor) {}

    record Day(long day, long weekday, long duration, long buffer,
            Map<String, List<NormalBooking>> taken) {}

    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9 -]+");
    private static final List<String> TRACE = List.of("normalised", "validated", "holiday-filter",
            "hours-and-lunch", "notice", "doctor-availability", "daily-cap", "booking-conflicts",
            "urgent-priority", "earliest-grid-slot");
    private static final Map<String, Timing> TIMINGS = Map.of("checkup", new Timing(20, 5),
            "consultation", new Timing(30, 10), "procedure", new Timing(60, 15));
    private static final long[][] OPENINGS = {{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
            {540, 1020}, {600, 840}, {0, 0}};

    /** Return the earliest valid appointment or the first validation error. */
    public static Object solution(Request request) {
        Clinic c = normaliseRequest(request);
        ClinicError e = validate(c);
        if (e != null) return e;
        Slot s = earliestSlot(c);
        if (s == null) return clinicError("NO_SLOT", null);
        return appointment(s);
    }

    private static Clinic normaliseRequest(Request r) {
        String p = trimmed(r.preferredDoctor());
        return buildClinic(r, p, normalisedDoctors(r.doctors()), normalisedBookings(r.bookings()));
    }

    private static Clinic buildClinic(Request r, String p, List<NormalDoctor> ds,
            List<NormalBooking> bs) {
        return new Clinic(r.nowDay(), r.nowMinute(), r.requestedDay(), r.horizonDays(),
                normalisedKind(r.kind()), r.urgent(), p, nameKeyOf(p), r.holidays(), ds, bs);
    }

    private static String trimmed(String s) { return s.strip(); }

    private static String normalisedKind(String s) { return s.strip().toLowerCase(Locale.ROOT); }

    private static String nameKeyOf(String s) { return normalisedNameKey(s); }

    private static String normalisedNameKey(String name) {
        if (name == null) return null;
        String c = name.strip();
        if (c.isEmpty() || !NAME.matcher(c).matches()) return null;
        return c.toLowerCase(Locale.ROOT);
    }

    private static List<NormalDoctor> normalisedDoctors(List<Doctor> ds) {
        List<NormalDoctor> out = new ArrayList<>();
        for (Doctor d : ds) out.add(normalisedDoctor(d));
        return out;
    }

    private static NormalDoctor normalisedDoctor(Doctor d) {
        String n = trimmed(d.name());
        return new NormalDoctor(n, nameKeyOf(n), d.windows());
    }

    private static List<NormalBooking> normalisedBookings(List<Booking> bs) {
        List<NormalBooking> out = new ArrayList<>();
        for (Booking b : bs) out.add(normalisedBooking(b));
        return out;
    }

    private static NormalBooking normalisedBooking(Booking b) {
        return new NormalBooking(b.day(), b.start(), b.end(), nameKeyOf(b.doctor()));
    }

    private static ClinicError validate(Clinic c) {
        ClinicError e = scalarError(c);
        if (e == null) e = doctorError(c);
        if (e == null) e = windowError(c);
        if (e == null) e = holidayError(c);
        return validateRemaining(c, e);
    }

    private static ClinicError validateRemaining(Clinic c, ClinicError e) {
        if (e == null) e = bookingError(c);
        if (e == null) e = orderError(c);
        return e;
    }

    private static ClinicError scalarError(Clinic c) {
        return daysInRange(c) && timesInRange(c) && TIMINGS.containsKey(c.kind()) ? null
                : clinicError("BAD_REQUEST", null);
    }

    private static boolean daysInRange(Clinic c) {
        return dayAllowed(c.nowDay()) && dayAllowed(c.requestedDay());
    }

    private static boolean dayAllowed(long d) { return dayWithinBounds(d); }

    private static boolean dayWithinBounds(long d) { return d >= 0 && d <= 1_000_000; }

    private static boolean timesInRange(Clinic c) {
        return c.nowMinute() >= 0 && c.nowMinute() <= 1439 && c.horizonDays() >= 0
                && c.horizonDays() <= 14;
    }

    private static ClinicError doctorError(Clinic c) {
        List<NormalDoctor> ds = c.doctors();
        if (ds.isEmpty() || ds.size() > 12) return clinicError("BAD_DOCTORS", null);
        return duplicateDoctorError(ds);
    }

    private static ClinicError duplicateDoctorError(List<NormalDoctor> ds) {
        Set<String> keys = new HashSet<>();
        for (int i = 0; i < ds.size(); i++) {
            String k = ds.get(i).key();
            if (k == null || !keys.add(k)) return clinicError("BAD_DOCTORS", i);
        }
        return null;
    }

    private static ClinicError windowError(Clinic c) {
        int i = 0;
        for (NormalDoctor d : c.doctors()) {
            if (invalidWindows(d.windows())) return clinicError("BAD_WINDOW", i);
            i++;
        }
        return null;
    }

    private static boolean invalidWindows(List<Window> ws) {
        if (ws.size() > 8) return true;
        for (Window w : ws) if (!windowValid(w)) return true;
        return false;
    }

    private static boolean windowValid(Window w) { return windowInRange(w); }

    private static boolean windowInRange(Window w) {
        return w.weekday() >= 0 && w.weekday() <= 6 && w.open() >= 0 && w.open() < w.close()
                && w.close() <= 1440;
    }

    private static ClinicError holidayError(Clinic c) {
        List<Long> hs = c.holidays();
        if (hs.size() > 60) return clinicError("BAD_HOLIDAY", null);
        return invalidHoliday(hs);
    }

    private static ClinicError invalidHoliday(List<Long> hs) {
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < hs.size(); i++) {
            if (!unseenDay(seen, hs.get(i))) return clinicError("BAD_HOLIDAY", i);
        }
        return null;
    }

    private static boolean unseenDay(Set<Long> seen, long d) {
        return d >= 0 && d <= 1_000_000 && seen.add(d);
    }

    private static ClinicError bookingError(Clinic c) {
        List<NormalBooking> bs = c.bookings();
        if (bs.size() > 200) return clinicError("BAD_BOOKING", null);
        return invalidBooking(bs, doctorKeys(c));
    }

    private static Set<String> doctorKeys(Clinic c) {
        Set<String> out = new HashSet<>();
        for (NormalDoctor d : c.doctors()) out.add(d.key());
        return out;
    }

    private static ClinicError invalidBooking(List<NormalBooking> bs, Set<String> names) {
        for (int i = 0; i < bs.size(); i++) {
            if (!bookingValid(bs.get(i), names)) return clinicError("BAD_BOOKING", i);
        }
        return null;
    }

    private static boolean bookingValid(NormalBooking b, Set<String> names) {
        return bookingInRange(b, names);
    }

    private static boolean bookingInRange(NormalBooking b, Set<String> names) {
        return b.day() >= 0 && b.day() <= 1_000_000 && b.start() >= 0 && b.start() < b.end()
                && b.end() <= 1440 && names.contains(b.key());
    }

    private static ClinicError orderError(Clinic c) {
        ClinicError e = unknownPreferredError(c);
        return e == null ? dayOrderError(c) : e;
    }

    private static ClinicError unknownPreferredError(Clinic c) {
        boolean miss = !c.preferredDoctor().isEmpty()
                && c.doctors().stream().noneMatch(d -> d.key().equals(c.preferredKey()));
        return miss ? clinicError("UNKNOWN_DOCTOR", null) : null;
    }

    private static ClinicError dayOrderError(Clinic c) {
        boolean out = c.requestedDay() < c.nowDay() || c.requestedDay() > c.nowDay() + 8;
        return out ? clinicError("BAD_DAY_ORDER", null) : null;
    }

    private static Slot earliestSlot(Clinic c) {
        Timing t = TIMINGS.get(c.kind());
        List<NormalDoctor> ds = eligibleDoctors(c);
        for (long day : candidateDays(c)) {
            Slot s = firstSlotOn(c, ds, dayContext(c, day, t));
            if (s != null) return s;
        }
        return null;
    }

    private static List<NormalDoctor> eligibleDoctors(Clinic c) {
        List<NormalDoctor> ds = new ArrayList<>(c.doctors());
        if (!c.urgent() && !c.preferredDoctor().isEmpty()) ds = preferredOnly(c, ds);
        ds.sort(Comparator.comparing(NormalDoctor::key));
        return ds;
    }

    private static List<NormalDoctor> preferredOnly(Clinic c, List<NormalDoctor> ds) {
        List<NormalDoctor> out = new ArrayList<>();
        for (NormalDoctor d : ds) if (d.key().equals(c.preferredKey())) out.add(d);
        return out;
    }

    private static List<Long> candidateDays(Clinic c) {
        long first = c.requestedDay();
        long last = lastCandidateDay(c, first);
        Set<Long> hol = new HashSet<>(c.holidays());
        return nonHolidayDays(first, last, hol);
    }

    private static long lastCandidateDay(Clinic c, long first) {
        return Math.min(Math.min(first + c.horizonDays(), first + 14), 1_000_000);
    }

    private static List<Long> nonHolidayDays(long first, long last, Set<Long> hol) {
        List<Long> out = new ArrayList<>();
        for (long day = first; day <= last; day++) if (!hol.contains(day)) out.add(day);
        return out;
    }

    private static Day dayContext(Clinic c, long day, Timing t) {
        return new Day(day, day % 7, t.duration(), t.buffer(), dailyBookings(c, day));
    }

    private static Map<String, List<NormalBooking>> dailyBookings(Clinic c, long day) {
        Map<String, List<NormalBooking>> out = new HashMap<>();
        for (NormalBooking b : c.bookings()) if (b.day() == day) addBooking(out, b);
        return out;
    }

    private static void addBooking(Map<String, List<NormalBooking>> out, NormalBooking b) {
        out.computeIfAbsent(b.key(), k -> new ArrayList<>()).add(b);
    }

    private static Slot firstSlotOn(Clinic c, List<NormalDoctor> ds, Day d) {
        for (long start = 0; start < 1440; start += 5) {
            Slot s = firstSlotAt(c, ds, d, start);
            if (s != null) return s;
        }
        return null;
    }

    private static Slot firstSlotAt(Clinic c, List<NormalDoctor> ds, Day d, long start) {
        long end = start + d.duration() + d.buffer();
        for (NormalDoctor m : ds) {
            if (slotAvailable(c, m, d, start, end)) return makeSlot(d, start, m);
        }
        return null;
    }

    private static boolean slotAvailable(Clinic c, NormalDoctor m, Day d, long start, long end) {
        return withinHours(m, d.weekday(), start, end) && scheduleClear(c, d, start, end, m);
    }

    private static boolean withinHours(NormalDoctor m, long weekday, long start, long end) {
        return windowContains(m, weekday, start, end) && withinOpening(weekday, start, end)
                && !overlapsLunch(start, end);
    }

    private static boolean windowContains(NormalDoctor m, long weekday, long start, long end) {
        for (Window w : m.windows()) {
            if (w.weekday() == weekday && w.open() <= start && end <= w.close()) return true;
        }
        return false;
    }

    private static boolean withinOpening(long weekday, long start, long end) {
        long[] o = OPENINGS[(int) weekday];
        return o[0] <= start && end <= o[1];
    }

    private static boolean overlapsLunch(long start, long end) { return start < 780 && end > 720; }

    private static boolean scheduleClear(Clinic c, Day d, long start, long end, NormalDoctor m) {
        List<NormalBooking> bs = doctorBookings(d, m);
        return afterNotice(c, d.day(), start) && bs.size() < 4 && noOverlap(start, end, bs);
    }

    private static List<NormalBooking> doctorBookings(Day d, NormalDoctor m) {
        return d.taken().getOrDefault(m.key(), List.of());
    }

    private static boolean afterNotice(Clinic c, long day, long start) {
        return day > c.nowDay() || start >= c.nowMinute() + 60;
    }

    private static boolean noOverlap(long start, long end, List<NormalBooking> bs) {
        for (NormalBooking b : bs) {
            if (start < b.end() && end > b.start()) return false;
        }
        return true;
    }

    private static Slot makeSlot(Day d, long start, NormalDoctor m) {
        return new Slot(d.day(), start, start + d.duration(), m.name());
    }

    private static Appointment appointment(Slot s) {
        return new Appointment(s.day(), s.start(), s.end(), s.doctor(), TRACE);
    }

    private static ClinicError clinicError(String code, Integer index) {
        return new ClinicError(code, index);
    }
}
