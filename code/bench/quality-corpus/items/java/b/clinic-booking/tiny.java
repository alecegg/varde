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
        Clinic c = norm(request);
        ClinicError e = check(c);
        if (e != null) return e;
        Slot s = slot(c);
        if (s == null) return err("NO_SLOT", null);
        return pack(s);
    }

    private static Clinic norm(Request r) {
        String p = pre(r.preferredDoctor());
        return fill(r, p, docs(r.doctors()), books(r.bookings()));
    }

    private static Clinic fill(Request r, String p, List<NormalDoctor> ds, List<NormalBooking> bs) {
        return new Clinic(r.nowDay(), r.nowMinute(), r.requestedDay(), r.horizonDays(),
                low(r.kind()), r.urgent(), p, keyOf(p), r.holidays(), ds, bs);
    }

    private static String pre(String s) { return s.strip(); }

    private static String low(String s) { return s.strip().toLowerCase(Locale.ROOT); }

    private static String keyOf(String s) { return nameKey(s); }

    private static String nameKey(String name) {
        if (name == null) return null;
        String c = name.strip();
        if (c.isEmpty() || !NAME.matcher(c).matches()) return null;
        return c.toLowerCase(Locale.ROOT);
    }

    private static List<NormalDoctor> docs(List<Doctor> ds) {
        List<NormalDoctor> out = new ArrayList<>();
        for (Doctor d : ds) out.add(doc(d));
        return out;
    }

    private static NormalDoctor doc(Doctor d) {
        String n = pre(d.name());
        return new NormalDoctor(n, keyOf(n), d.windows());
    }

    private static List<NormalBooking> books(List<Booking> bs) {
        List<NormalBooking> out = new ArrayList<>();
        for (Booking b : bs) out.add(book(b));
        return out;
    }

    private static NormalBooking book(Booking b) {
        return new NormalBooking(b.day(), b.start(), b.end(), keyOf(b.doctor()));
    }

    private static ClinicError check(Clinic c) {
        ClinicError e = scalars(c);
        if (e == null) e = docErr(c);
        if (e == null) e = winErr(c);
        if (e == null) e = holErr(c);
        return tail(c, e);
    }

    private static ClinicError tail(Clinic c, ClinicError e) {
        if (e == null) e = bookErr(c);
        if (e == null) e = orderErr(c);
        return e;
    }

    private static ClinicError scalars(Clinic c) {
        return bounds(c) && times(c) && TIMINGS.containsKey(c.kind()) ? null
                : err("BAD_REQUEST", null);
    }

    private static boolean bounds(Clinic c) {
        return inDay(c.nowDay()) && inDay(c.requestedDay());
    }

    private static boolean inDay(long d) { return dayInRange(d); }

    private static boolean dayInRange(long d) { return d >= 0 && d <= 1_000_000; }

    private static boolean times(Clinic c) {
        return c.nowMinute() >= 0 && c.nowMinute() <= 1439 && c.horizonDays() >= 0
                && c.horizonDays() <= 14;
    }

    private static ClinicError docErr(Clinic c) {
        List<NormalDoctor> ds = c.doctors();
        if (ds.isEmpty() || ds.size() > 12) return err("BAD_DOCTORS", null);
        return dupDoc(ds);
    }

    private static ClinicError dupDoc(List<NormalDoctor> ds) {
        Set<String> keys = new HashSet<>();
        for (int i = 0; i < ds.size(); i++) {
            String k = ds.get(i).key();
            if (k == null || !keys.add(k)) return err("BAD_DOCTORS", i);
        }
        return null;
    }

    private static ClinicError winErr(Clinic c) {
        int i = 0;
        for (NormalDoctor d : c.doctors()) {
            if (badWin(d.windows())) return err("BAD_WINDOW", i);
            i++;
        }
        return null;
    }

    private static boolean badWin(List<Window> ws) {
        if (ws.size() > 8) return true;
        for (Window w : ws) if (!winOk(w)) return true;
        return false;
    }

    private static boolean winOk(Window w) { return windowOk(w); }

    private static boolean windowOk(Window w) {
        return w.weekday() >= 0 && w.weekday() <= 6 && w.open() >= 0 && w.open() < w.close()
                && w.close() <= 1440;
    }

    private static ClinicError holErr(Clinic c) {
        List<Long> hs = c.holidays();
        if (hs.size() > 60) return err("BAD_HOLIDAY", null);
        return holAt(hs);
    }

    private static ClinicError holAt(List<Long> hs) {
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < hs.size(); i++) {
            if (!fresh(seen, hs.get(i))) return err("BAD_HOLIDAY", i);
        }
        return null;
    }

    private static boolean fresh(Set<Long> seen, long d) {
        return d >= 0 && d <= 1_000_000 && seen.add(d);
    }

    private static ClinicError bookErr(Clinic c) {
        List<NormalBooking> bs = c.bookings();
        if (bs.size() > 200) return err("BAD_BOOKING", null);
        return bookAt(bs, nameSet(c));
    }

    private static Set<String> nameSet(Clinic c) {
        Set<String> out = new HashSet<>();
        for (NormalDoctor d : c.doctors()) out.add(d.key());
        return out;
    }

    private static ClinicError bookAt(List<NormalBooking> bs, Set<String> names) {
        for (int i = 0; i < bs.size(); i++) {
            if (!bookOk(bs.get(i), names)) return err("BAD_BOOKING", i);
        }
        return null;
    }

    private static boolean bookOk(NormalBooking b, Set<String> names) {
        return bookingOk(b, names);
    }

    private static boolean bookingOk(NormalBooking b, Set<String> names) {
        return b.day() >= 0 && b.day() <= 1_000_000 && b.start() >= 0 && b.start() < b.end()
                && b.end() <= 1440 && names.contains(b.key());
    }

    private static ClinicError orderErr(Clinic c) {
        ClinicError e = unknown(c);
        return e == null ? badOrder(c) : e;
    }

    private static ClinicError unknown(Clinic c) {
        boolean miss = !c.preferredDoctor().isEmpty()
                && c.doctors().stream().noneMatch(d -> d.key().equals(c.preferredKey()));
        return miss ? err("UNKNOWN_DOCTOR", null) : null;
    }

    private static ClinicError badOrder(Clinic c) {
        boolean out = c.requestedDay() < c.nowDay() || c.requestedDay() > c.nowDay() + 8;
        return out ? err("BAD_DAY_ORDER", null) : null;
    }

    private static Slot slot(Clinic c) {
        Timing t = TIMINGS.get(c.kind());
        List<NormalDoctor> ds = pick(c);
        for (long day : openDays(c)) {
            Slot s = firstOn(c, ds, at(c, day, t));
            if (s != null) return s;
        }
        return null;
    }

    private static List<NormalDoctor> pick(Clinic c) {
        List<NormalDoctor> ds = new ArrayList<>(c.doctors());
        if (!c.urgent() && !c.preferredDoctor().isEmpty()) ds = only(c, ds);
        ds.sort(Comparator.comparing(NormalDoctor::key));
        return ds;
    }

    private static List<NormalDoctor> only(Clinic c, List<NormalDoctor> ds) {
        List<NormalDoctor> out = new ArrayList<>();
        for (NormalDoctor d : ds) if (d.key().equals(c.preferredKey())) out.add(d);
        return out;
    }

    private static List<Long> openDays(Clinic c) {
        long first = c.requestedDay();
        long last = lastDay(c, first);
        Set<Long> hol = new HashSet<>(c.holidays());
        return span(first, last, hol);
    }

    private static long lastDay(Clinic c, long first) {
        return Math.min(Math.min(first + c.horizonDays(), first + 14), 1_000_000);
    }

    private static List<Long> span(long first, long last, Set<Long> hol) {
        List<Long> out = new ArrayList<>();
        for (long day = first; day <= last; day++) if (!hol.contains(day)) out.add(day);
        return out;
    }

    private static Day at(Clinic c, long day, Timing t) {
        return new Day(day, day % 7, t.duration(), t.buffer(), daily(c, day));
    }

    private static Map<String, List<NormalBooking>> daily(Clinic c, long day) {
        Map<String, List<NormalBooking>> out = new HashMap<>();
        for (NormalBooking b : c.bookings()) if (b.day() == day) push(out, b);
        return out;
    }

    private static void push(Map<String, List<NormalBooking>> out, NormalBooking b) {
        out.computeIfAbsent(b.key(), k -> new ArrayList<>()).add(b);
    }

    private static Slot firstOn(Clinic c, List<NormalDoctor> ds, Day d) {
        for (long start = 0; start < 1440; start += 5) {
            Slot s = cell(c, ds, d, start);
            if (s != null) return s;
        }
        return null;
    }

    private static Slot cell(Clinic c, List<NormalDoctor> ds, Day d, long start) {
        long end = start + d.duration() + d.buffer();
        for (NormalDoctor m : ds) {
            if (usable(c, m, d, start, end)) return spot(d, start, m);
        }
        return null;
    }

    private static boolean usable(Clinic c, NormalDoctor m, Day d, long start, long end) {
        return fits(m, d.weekday(), start, end) && clear(c, d, start, end, m);
    }

    private static boolean fits(NormalDoctor m, long weekday, long start, long end) {
        return windowMatch(m, weekday, start, end) && openingOk(weekday, start, end)
                && !lunch(start, end);
    }

    private static boolean windowMatch(NormalDoctor m, long weekday, long start, long end) {
        for (Window w : m.windows()) {
            if (w.weekday() == weekday && w.open() <= start && end <= w.close()) return true;
        }
        return false;
    }

    private static boolean openingOk(long weekday, long start, long end) {
        long[] o = OPENINGS[(int) weekday];
        return o[0] <= start && end <= o[1];
    }

    private static boolean lunch(long start, long end) { return start < 780 && end > 720; }

    private static boolean clear(Clinic c, Day d, long start, long end, NormalDoctor m) {
        List<NormalBooking> bs = held(d, m);
        return notice(c, d.day(), start) && bs.size() < 4 && free(start, end, bs);
    }

    private static List<NormalBooking> held(Day d, NormalDoctor m) {
        return d.taken().getOrDefault(m.key(), List.of());
    }

    private static boolean notice(Clinic c, long day, long start) {
        return day > c.nowDay() || start >= c.nowMinute() + 60;
    }

    private static boolean free(long start, long end, List<NormalBooking> bs) {
        for (NormalBooking b : bs) {
            if (start < b.end() && end > b.start()) return false;
        }
        return true;
    }

    private static Slot spot(Day d, long start, NormalDoctor m) {
        return new Slot(d.day(), start, start + d.duration(), m.name());
    }

    private static Appointment pack(Slot s) {
        return new Appointment(s.day(), s.start(), s.end(), s.doctor(), TRACE);
    }

    private static ClinicError err(String code, Integer index) {
        return new ClinicError(code, index);
    }
}
