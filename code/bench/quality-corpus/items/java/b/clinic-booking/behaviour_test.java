import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.SplittableRandom;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Pattern;

public class behaviour_test {
    static final Pattern NAME = Pattern.compile("[A-Za-z0-9 -]+");
    static final List<String> TRACE = List.of("normalised", "validated", "holiday-filter",
            "hours-and-lunch", "notice", "doctor-availability", "daily-cap", "booking-conflicts",
            "urgent-priority", "earliest-grid-slot");

    record Candidate(long day, long start, String key, String name, long end) {}

    static final class Spec {
        long nowDay = 100;
        long nowMinute = 480;
        long requestedDay = 100;
        long horizonDays = 2;
        String kind = "checkup";
        boolean urgent;
        String preferred = "";
        List<Long> holidays = new ArrayList<>();
        List<solution.Doctor> doctors = new ArrayList<>(List.of(weekdays("Ada")));
        List<solution.Booking> bookings = new ArrayList<>();

        Spec nowDay(long value) { nowDay = value; return this; }
        Spec nowMinute(long value) { nowMinute = value; return this; }
        Spec requested(long value) { requestedDay = value; return this; }
        Spec horizon(long value) { horizonDays = value; return this; }
        Spec kind(String value) { kind = value; return this; }
        Spec urgent(boolean value) { urgent = value; return this; }
        Spec preferred(String value) { preferred = value; return this; }
        Spec holidays(long... days) { holidays = boxed(days); return this; }
        Spec holidays(List<Long> days) { holidays = new ArrayList<>(days); return this; }
        Spec doctors(solution.Doctor... values) {
            doctors = new ArrayList<>(List.of(values));
            return this;
        }
        Spec doctors(List<solution.Doctor> values) {
            doctors = new ArrayList<>(values);
            return this;
        }
        Spec bookings(solution.Booking... values) {
            bookings = new ArrayList<>(List.of(values));
            return this;
        }
        Spec bookings(List<solution.Booking> values) {
            bookings = new ArrayList<>(values);
            return this;
        }

        solution.Request done() {
            return new solution.Request(nowDay, nowMinute, requestedDay, horizonDays, kind, urgent,
                    preferred, holidays, doctors, bookings);
        }
    }

    public static void main(String[] args) {
        worked();
        errorPrecedence();
        boundaries();
        randomCases();
        System.out.println("behaviour cases passed");
    }

    static List<Long> boxed(long... days) {
        List<Long> values = new ArrayList<>();
        for (long day : days) values.add(day);
        return values;
    }

    static solution.Doctor doctor(String name, long... triples) {
        List<solution.Window> windows = new ArrayList<>();
        for (int index = 0; index < triples.length; index += 3) {
            windows.add(new solution.Window(triples[index], triples[index + 1],
                    triples[index + 2]));
        }
        return new solution.Doctor(name, windows);
    }

    static solution.Doctor weekdays(String name) {
        return doctor(name, 0, 540, 1020, 1, 540, 1020, 2, 540, 1020, 3, 540, 1020, 4, 540, 1020);
    }

    static solution.Doctor nineWindows(String name) {
        long[] triples = new long[27];
        for (int index = 0; index < 9; index++) {
            triples[index * 3] = 2;
            triples[index * 3 + 1] = 540;
            triples[index * 3 + 2] = 600;
        }
        return doctor(name, triples);
    }

    static solution.Booking booking(long day, long start, long end, String doctor) {
        return new solution.Booking(day, start, end, doctor);
    }

    static List<solution.Booking> spans(long day, String doctor, long... starts) {
        List<solution.Booking> bookings = new ArrayList<>();
        for (long start : starts) bookings.add(booking(day, start, start + 10, doctor));
        return bookings;
    }

    static solution.Appointment at(long day, long start, long end) {
        return at(day, start, end, "Ada");
    }

    static solution.Appointment at(long day, long start, long end, String name) {
        return new solution.Appointment(day, start, end, name, TRACE);
    }

    static solution.ClinicError error(String code) {
        return new solution.ClinicError(code, null);
    }

    static solution.ClinicError error(String code, int index) {
        return new solution.ClinicError(code, index);
    }

    // Every fixed expectation is also checked against the brute-force oracle.
    static void check(solution.Request request, Object expected) {
        Object actual = solution.solution(request);
        if (!expected.equals(actual)) {
            throw new AssertionError("expected=" + expected + " actual=" + actual + " " + request);
        }
        Object fromOracle = oracle(request);
        if (!expected.equals(fromOracle)) {
            throw new AssertionError("oracle=" + fromOracle + " expected=" + expected + " "
                    + request);
        }
    }

    static void check(solution.Request request) {
        Object expected = oracle(request);
        Object actual = solution.solution(request);
        if (!expected.equals(actual)) {
            throw new AssertionError("oracle=" + expected + " actual=" + actual + " " + request);
        }
    }

    static void worked() {
        check(new Spec().done(), at(100, 540, 560));
        check(new Spec().kind("  CONSULTATION  ").done(), at(100, 540, 570));
        check(new Spec().nowMinute(500).done(), at(100, 560, 580));
        check(new Spec().nowMinute(1000).done(), at(101, 540, 560));
        check(new Spec().kind("consultation").done(), at(100, 540, 570));
        check(new Spec().kind("procedure").done(), at(100, 540, 600));
        check(new Spec().doctors(doctor("  Ada  ", 2, 600, 660)).done(), at(100, 600, 620));
        check(new Spec().doctors(doctor("Ada", 2, 700, 840)).done(), at(100, 780, 800));
        check(new Spec().bookings(booking(100, 540, 570, "  ADA  ")).done(), at(100, 570, 590));
        check(new Spec().bookings(booking(100, 540, 565, "Ada")).done(), at(100, 565, 585));
        check(new Spec().bookings(spans(100, "Ada", 540, 560, 580, 600)).done(),
                at(101, 540, 560));
        check(new Spec().holidays(100).done(), at(101, 540, 560));
        check(new Spec().doctors(doctor("Bo", 2, 540, 1020), doctor("Ada", 2, 540, 1020)).done(),
                at(100, 540, 560));
    }

    static void errorPrecedence() {
        check(new Spec().nowDay(-1).done(), error("BAD_REQUEST"));
        check(new Spec().nowDay(1_000_001).done(), error("BAD_REQUEST"));
        check(new Spec().horizon(15).done(), error("BAD_REQUEST"));
        check(new Spec().nowMinute(1440).done(), error("BAD_REQUEST"));
        check(new Spec().requested(1_000_001).done(), error("BAD_REQUEST"));
        check(new Spec().kind("other").doctors(List.of()).done(), error("BAD_REQUEST"));
        check(new Spec().doctors(List.of()).done(), error("BAD_DOCTORS"));
        check(new Spec().doctors(doctor("Ada", 7, 540, 600), doctor(" ada ")).done(),
                error("BAD_DOCTORS", 1));
        check(new Spec().doctors(doctor("Ada"), doctor("Bo"),
                doctor("Cy", 2, 900, 900)).done(), error("BAD_WINDOW", 2));
        check(new Spec().doctors(doctor("Ada", 2, 540, 1441)).done(), error("BAD_WINDOW", 0));
        check(new Spec().doctors(doctor("Ada", 2, 700, 700)).holidays(-1).done(),
                error("BAD_WINDOW", 0));
        check(new Spec().doctors(nineWindows("Ada")).done(), error("BAD_WINDOW", 0));
        check(new Spec().holidays(100, 100).done(), error("BAD_HOLIDAY", 1));
        check(new Spec().holidays(1_000_001).done(), error("BAD_HOLIDAY", 0));
        check(new Spec().holidays(-1).bookings(booking(100, 540, 540, "Ada")).done(),
                error("BAD_HOLIDAY", 0));
        check(new Spec().bookings(booking(100, 540, 550, "Ada"),
                booking(100, 540, 540, "Ada")).done(), error("BAD_BOOKING", 1));
        check(new Spec().bookings(booking(100, 540, 550, "Ada"),
                booking(100, 550, 560, "Ada"), booking(100, 560, 560, "Ada")).done(),
                error("BAD_BOOKING", 2));
        check(new Spec().bookings(booking(100, 540, 550, "Missing")).done(),
                error("BAD_BOOKING", 0));
        check(new Spec().bookings(booking(100, 540, 1441, "Ada")).done(), error("BAD_BOOKING", 0));
        check(new Spec().bookings(booking(-1, 540, 550, "Ada")).done(), error("BAD_BOOKING", 0));
        check(new Spec().bookings(booking(100, -1, 550, "Ada")).done(), error("BAD_BOOKING", 0));
        check(new Spec().bookings(booking(1_000_001, 540, 550, "Ada")).done(),
                error("BAD_BOOKING", 0));
        check(new Spec().bookings(booking(100, 1, 1, "Ada")).preferred("Bo").done(),
                error("BAD_BOOKING", 0));
        check(new Spec().preferred("Bo").done(), error("UNKNOWN_DOCTOR"));
        check(new Spec().preferred("Missing").requested(101).done(), error("UNKNOWN_DOCTOR"));
        check(new Spec().requested(99).preferred("Bo").done(), error("UNKNOWN_DOCTOR"));
        check(new Spec().requested(99).done(), error("BAD_DAY_ORDER"));
        check(new Spec().requested(109).done(), error("BAD_DAY_ORDER"));
        check(new Spec().requested(99).holidays(100, 100).done(), error("BAD_HOLIDAY", 1));
        check(new Spec().doctors(doctor("Ada@")).done(), error("BAD_DOCTORS", 0));
        check(new Spec().doctors(doctor("Ada"), doctor("ada")).holidays(-1).done(),
                error("BAD_DOCTORS", 1));
        List<solution.Doctor> thirteen = new ArrayList<>();
        for (int index = 0; index < 13; index++) thirteen.add(doctor("D" + index));
        check(new Spec().doctors(thirteen).done(), error("BAD_DOCTORS"));
        List<Long> sixtyOne = new ArrayList<>();
        for (long day = 200; day < 261; day++) sixtyOne.add(day);
        check(new Spec().holidays(sixtyOne).done(), error("BAD_HOLIDAY"));
        List<solution.Booking> many = new ArrayList<>();
        for (int index = 0; index < 201; index++) many.add(booking(500 + index, 0, 1, "Ada"));
        check(new Spec().bookings(many).done(), error("BAD_BOOKING"));
        check(new Spec().doctors(doctor("Ada", 1, 540, 1020)).done(), error("NO_SLOT"));
    }

    static void boundaries() {
        for (long open : new long[]{599, 600, 655}) {
            check(new Spec().doctors(doctor("Ada", 2, open, 685)).done());
        }
        check(new Spec().nowMinute(480).done(), at(100, 540, 560));
        check(new Spec().nowMinute(481).done(), at(100, 545, 565));
        check(new Spec().horizon(0).done(), at(100, 540, 560));
        check(new Spec().horizon(0).holidays(100).done(), error("NO_SLOT"));
        check(new Spec().nowDay(0).nowMinute(0).requested(0).horizon(0).done(),
                at(0, 540, 560));
        check(new Spec().doctors(doctor("Ada")).done(), error("NO_SLOT"));
        check(new Spec().requested(108).horizon(0).done(), at(108, 540, 560));
        check(new Spec().requested(102).horizon(0).done(), at(102, 540, 560));
        check(new Spec().requested(103).horizon(0)
                .doctors(doctor("Ada", 5, 600, 840)).done(), at(103, 600, 620));
        check(new Spec().requested(103).horizon(0).doctors(doctor("Ada", 5, 600, 840))
                .bookings(booking(103, 600, 815, "Ada")).done(), at(103, 815, 835));
        check(new Spec().bookings(booking(100, 1400, 1440, "Ada")).done(), at(100, 540, 560));
        check(new Spec().doctors(doctor("Ada", 2, 540, 565)).done(), at(100, 540, 560));
        check(new Spec().doctors(doctor("Ada", 2, 600, 625)).done(), at(100, 600, 620));
        check(new Spec().horizon(0).doctors(doctor("Ada", 2, 540, 564)).done(), error("NO_SLOT"));
        check(new Spec().horizon(0).doctors(doctor("Ada", 2, 800, 900))
                .bookings(spans(100, "Ada", 540, 560, 580, 600)).done(), error("NO_SLOT"));
        check(new Spec().doctors(doctor("Ada", 2, 995, 1020)).done(), at(100, 995, 1015));
        check(new Spec().nowDay(0).requested(0).horizon(0)
                .bookings(booking(0, 540, 995, "Ada")).done(), at(0, 995, 1015));
        check(new Spec().horizon(0).bookings(booking(100, 540, 995, "Ada")).done(),
                at(100, 995, 1015));
        check(new Spec().requested(102).horizon(0)
                .bookings(booking(102, 540, 995, "Ada")).done(), at(102, 995, 1015));
        check(new Spec().requested(104).horizon(0)
                .doctors(doctor("Ada", 6, 0, 1020)).done(), error("NO_SLOT"));
        check(new Spec().bookings(booking(100, 540, 695, "Ada")).done(), at(100, 695, 715));
        check(new Spec().bookings(booking(100, 540, 696, "Ada")).done(), at(100, 780, 800));
        check(new Spec().doctors(doctor("Ada", 2, 695, 1020)).done(), at(100, 695, 715));
        check(new Spec().nowMinute(636).kind("procedure").done(), at(100, 780, 840));
        check(new Spec().doctors(doctor("Ada", 2, 540, 1020), doctor("Bo", 2, 540, 1020))
                .bookings(spans(100, "Ada", 800, 820, 840, 860)).done(), at(100, 540, 560, "Bo"));
        check(new Spec().doctors(doctor("Ada", 2, 800, 900), doctor("Bo", 2, 540, 1020))
                .bookings(booking(100, 540, 570, "Bo"), booking(100, 560, 590, "Bo"),
                        booking(100, 580, 610, "Bo"), booking(100, 600, 630, "Bo")).done(),
                at(100, 800, 820));
        check(new Spec().doctors(doctor("Ada", 2, 540, 1020))
                .bookings(spans(100, "Ada", 540, 560, 580, 600)).horizon(0).done(),
                error("NO_SLOT"));
        check(new Spec().bookings(booking(100, 540, 555, "Ada")).done(), at(100, 555, 575));
        check(new Spec().bookings(booking(100, 565, 575, "Ada")).done(), at(100, 540, 560));
        check(new Spec().horizon(0).doctors(doctor("Ada", 2, 575, 600))
                .bookings(booking(100, 550, 575, "Ada")).done(), at(100, 575, 595));
        check(new Spec().bookings(spans(100, "Ada", 800, 850, 900)).done(), at(100, 540, 560));
        check(new Spec().doctors(doctor("zoe", 2, 540, 1020), doctor("ada", 2, 540, 1020))
                .done(), at(100, 540, 560, "ada"));
        check(new Spec().doctors(doctor("BO", 2, 540, 1020), doctor("ada", 2, 540, 1020))
                .done(), at(100, 540, 560, "ada"));
        check(new Spec().doctors(doctor("Ada", 2, 540, 1020, 2, 540, 1020, 2, 540, 1020,
                2, 540, 1020, 2, 540, 1020, 2, 540, 1020, 2, 540, 1020, 2, 540, 1020)).done(),
                at(100, 540, 560));
        List<Long> sixty = new ArrayList<>();
        for (long day = 200; day < 260; day++) sixty.add(day);
        check(new Spec().holidays(sixty).done(), at(100, 540, 560));
        List<solution.Booking> twoHundred = new ArrayList<>();
        for (int index = 0; index < 200; index++) {
            twoHundred.add(booking(500 + index, 0, 1, "Ada"));
        }
        check(new Spec().bookings(twoHundred).done(), at(100, 540, 560));
        List<solution.Doctor> twelve = new ArrayList<>();
        for (int index = 0; index < 12; index++) twelve.add(doctor("Doc " + index, 2, 540, 1020));
        check(new Spec().doctors(twelve).done(), at(100, 540, 560, "Doc 0"));
        check(new Spec().horizon(14).done(), at(100, 540, 560));
        check(new Spec().nowMinute(1439).done(), at(101, 540, 560));
        check(new Spec().holidays(100, 101).done(), at(102, 540, 560));
        check(new Spec().bookings(booking(100, 0, 1, "ada")).done(), at(100, 540, 560));
        check(new Spec().preferred(" ada ").done(), at(100, 540, 560));
        check(new Spec().nowDay(999_992).requested(1_000_000).horizon(14).done(),
                at(1_000_000, 540, 560));
        check(new Spec().nowDay(1_000_000).requested(1_000_000).horizon(0).done(),
                at(1_000_000, 540, 560));
        check(new Spec().preferred("Bo").doctors(doctor("Bo", 2, 540, 1020),
                doctor("Ada", 2, 540, 1020)).done(), at(100, 540, 560, "Bo"));
        check(new Spec().preferred("Bo").urgent(true).doctors(doctor("Bo", 2, 540, 1020),
                doctor("Ada", 2, 540, 1020)).done(), at(100, 540, 560, "Ada"));
        List<Long> blocked = new ArrayList<>();
        for (long day = 100; day < 114; day++) blocked.add(day);
        check(new Spec().horizon(14).holidays(blocked).done(), at(114, 540, 560));
    }

    // This oracle enumerates each day, doctor and grid point without implementation helpers.
    static Object oracle(solution.Request request) {
        long nowDay = request.nowDay();
        long nowMinute = request.nowMinute();
        long requestedDay = request.requestedDay();
        long horizon = request.horizonDays();
        String kind = request.kind().strip().toLowerCase(Locale.ROOT);
        boolean knownKind = kind.equals("checkup") || kind.equals("consultation")
                || kind.equals("procedure");
        boolean scalarsOk = nowDay >= 0 && nowDay <= 1_000_000
                && requestedDay >= 0 && requestedDay <= 1_000_000
                && nowMinute >= 0 && nowMinute <= 1439 && horizon >= 0 && horizon <= 14;
        if (!scalarsOk || !knownKind) return error("BAD_REQUEST");

        List<solution.Doctor> doctors = request.doctors();
        if (doctors.isEmpty() || doctors.size() > 12) return error("BAD_DOCTORS");
        List<String> keys = new ArrayList<>();
        for (int index = 0; index < doctors.size(); index++) {
            String name = doctors.get(index).name().strip();
            if (name.isEmpty() || !NAME.matcher(name).matches()) return error("BAD_DOCTORS", index);
            String key = name.toLowerCase(Locale.ROOT);
            if (keys.contains(key)) return error("BAD_DOCTORS", index);
            keys.add(key);
        }
        for (int index = 0; index < doctors.size(); index++) {
            List<solution.Window> windows = doctors.get(index).windows();
            if (windows.size() > 8) return error("BAD_WINDOW", index);
            for (solution.Window window : windows) {
                if (window.weekday() < 0 || window.weekday() > 6 || window.open() < 0
                        || window.open() >= window.close() || window.close() > 1440) {
                    return error("BAD_WINDOW", index);
                }
            }
        }
        List<Long> holidays = request.holidays();
        if (holidays.size() > 60) return error("BAD_HOLIDAY");
        Set<Long> holidaySet = new HashSet<>();
        for (int index = 0; index < holidays.size(); index++) {
            long day = holidays.get(index);
            if (day < 0 || day > 1_000_000 || !holidaySet.add(day)) {
                return error("BAD_HOLIDAY", index);
            }
        }
        List<solution.Booking> bookings = request.bookings();
        if (bookings.size() > 200) return error("BAD_BOOKING");
        for (int index = 0; index < bookings.size(); index++) {
            solution.Booking booking = bookings.get(index);
            String key = booking.doctor().strip().toLowerCase(Locale.ROOT);
            if (booking.day() < 0 || booking.day() > 1_000_000 || booking.start() < 0
                    || booking.start() >= booking.end() || booking.end() > 1440
                    || !keys.contains(key)) {
                return error("BAD_BOOKING", index);
            }
        }
        String preferred = request.preferredDoctor().strip().toLowerCase(Locale.ROOT);
        if (!preferred.isEmpty() && !keys.contains(preferred)) return error("UNKNOWN_DOCTOR");
        if (requestedDay < nowDay || requestedDay > nowDay + 8) return error("BAD_DAY_ORDER");

        long duration = kind.equals("checkup") ? 20 : kind.equals("consultation") ? 30 : 60;
        long buffer = kind.equals("checkup") ? 5 : kind.equals("consultation") ? 10 : 15;
        long last = Math.min(Math.min(requestedDay + horizon, requestedDay + 14), 1_000_000);
        List<Candidate> candidates = new ArrayList<>();
        for (long day = requestedDay; day <= last; day++) {
            if (holidaySet.contains(day)) continue;
            long weekday = day % 7;
            long open = weekday < 5 ? 540 : weekday == 5 ? 600 : 0;
            long close = weekday < 5 ? 1020 : weekday == 5 ? 840 : 0;
            for (int index = 0; index < doctors.size(); index++) {
                String key = keys.get(index);
                if (!request.urgent() && !preferred.isEmpty() && !key.equals(preferred)) continue;
                long sameDoctorDay = 0;
                for (solution.Booking booking : bookings) {
                    String booked = booking.doctor().strip().toLowerCase(Locale.ROOT);
                    if (booking.day() == day && booked.equals(key)) sameDoctorDay++;
                }
                if (sameDoctorDay >= 4) continue;
                for (long start = 0; start <= 1435; start += 5) {
                    long occupiedEnd = start + duration + buffer;
                    if (day == nowDay && start < nowMinute + 60) continue;
                    if (start < open || occupiedEnd > close) continue;
                    if (start < 780 && occupiedEnd > 720) continue;
                    boolean windowFits = false;
                    for (solution.Window window : doctors.get(index).windows()) {
                        windowFits = windowFits || (window.weekday() == weekday
                                && window.open() <= start && occupiedEnd <= window.close());
                    }
                    if (!windowFits) continue;
                    boolean clear = true;
                    for (solution.Booking booking : bookings) {
                        String booked = booking.doctor().strip().toLowerCase(Locale.ROOT);
                        boolean sameBooking = booking.day() == day && booked.equals(key);
                        clear = clear && (!sameBooking
                                || start >= booking.end() || occupiedEnd <= booking.start());
                    }
                    if (!clear) continue;
                    candidates.add(new Candidate(day, start, key,
                            doctors.get(index).name().strip(), start + duration));
                }
            }
        }
        candidates.sort(Comparator.comparingLong(Candidate::day)
                .thenComparingLong(Candidate::start).thenComparing(Candidate::key));
        if (candidates.isEmpty()) return error("NO_SLOT");
        Candidate chosen = candidates.get(0);
        return new solution.Appointment(chosen.day(), chosen.start(), chosen.end(), chosen.name(),
                TRACE);
    }

    static final String[] KINDS = {"checkup", "consultation", "procedure"};
    static final String[] BAD_KINDS = {"other", "Checkup", "", "consult"};
    static final String[] NAMES = {"Ada", "Bo", "Cy"};
    static final String[] UNKNOWN = {"Missing", "Zed"};
    static final String[] BAD_BOOKING_DOCTORS = {"Ghost", "", "Ada@"};
    static final long[] STARTS = {540, 560, 580, 600, 620, 640, 660, 680, 700, 760, 780, 800, 820};
    static final long[] LENGTHS = {10, 20, 30, 60};

    static String pick(SplittableRandom g, String[] good, String[] bad, int badChance) {
        return g.nextInt(1000) < 1000 - badChance ? good[g.nextInt(good.length)]
                : bad[g.nextInt(bad.length)];
    }

    static solution.Doctor randomDoctor(SplittableRandom g, String name) {
        if (g.nextInt(100) < 4) return doctor(name);
        List<solution.Window> windows = new ArrayList<>();
        for (long weekday = 0; weekday < 7; weekday++) {
            if (g.nextInt(4) == 0) continue;
            long open = weekday == 5 ? 600 : 540;
            long close = weekday == 5 ? 840 : 1020;
            windows.add(new solution.Window(weekday, open, close));
        }
        return new solution.Doctor(name, windows);
    }

    static String randomSpelling(SplittableRandom g, String name) {
        return switch (g.nextInt(5)) {
            case 0 -> " " + name + " ";
            case 1 -> name.toUpperCase(Locale.ROOT);
            case 2 -> name.toLowerCase(Locale.ROOT);
            default -> name;
        };
    }

    static solution.Doctor badDoctor(SplittableRandom g) {
        return switch (g.nextInt(5)) {
            case 0 -> doctor("ada", 2, 540, 1020);
            case 1 -> doctor("W1", 7, 540, 1020);
            case 2 -> doctor("W2", 2, 540, 1441);
            case 3 -> nineWindows("W3");
            default -> doctor("Ada@", 2, 540, 1020);
        };
    }

    static solution.Booking badBooking(SplittableRandom g, long day) {
        return switch (g.nextInt(4)) {
            case 0 -> booking(day, 600, 600, "Ada");
            case 1 -> booking(day, -5, 30, "Ada");
            case 2 -> booking(day, 600, 1441, "Ada");
            default -> booking(1_000_001, 600, 640, "Ada");
        };
    }

    static solution.Request randomRequest(SplittableRandom g) {
        long nowDay = 20 + g.nextInt(880);
        long requestedDay = nowDay + g.nextInt(0, 9);
        long horizon = g.nextInt(0, 15);
        Spec spec = new Spec().nowDay(nowDay).nowMinute(g.nextInt(0, 1440))
                .requested(requestedDay).horizon(horizon).urgent(g.nextInt(2) == 0)
                .kind(pick(g, KINDS, BAD_KINDS, 15));
        List<solution.Doctor> panels = new ArrayList<>();
        int doctorCount = 1 + g.nextInt(3);
        for (int index = 0; index < doctorCount; index++) {
            panels.add(randomDoctor(g, NAMES[index]));
        }
        if (g.nextInt(100) < 7) panels.add(badDoctor(g));
        if (g.nextInt(400) == 0) {
            while (panels.size() < 13) panels.add(doctor("D" + panels.size(), 2, 540, 1020));
        }
        spec.doctors(panels);
        String[] spellings = new String[doctorCount];
        for (int index = 0; index < doctorCount; index++) {
            spellings[index] = randomSpelling(g, NAMES[index]);
        }
        boolean unknownPreference = g.nextInt(100) < 6;
        String chosen = unknownPreference ? UNKNOWN[g.nextInt(UNKNOWN.length)]
                : randomSpelling(g, NAMES[g.nextInt(doctorCount)]);
        spec.preferred(g.nextInt(4) == 0 ? "" : chosen);

        Set<Long> distinct = new HashSet<>();
        int holidayCount = g.nextInt(0, 4);
        for (int index = 0; index < holidayCount; index++) {
            distinct.add(requestedDay + g.nextInt(0, (int) horizon + 1));
        }
        List<Long> holidays = new ArrayList<>(distinct);
        if (!holidays.isEmpty() && g.nextInt(100) < 6) holidays.add(holidays.get(0));
        if (g.nextInt(500) == 0) holidays.add(1_000_001L);
        if (g.nextInt(300) == 0) {
            holidays.clear();
            for (long day = 200; day < 261; day++) holidays.add(day);
        }
        spec.holidays(holidays);

        List<solution.Booking> stays = new ArrayList<>();
        int bookingCount = g.nextInt(0, 7);
        for (int index = 0; index < bookingCount; index++) {
            long day = requestedDay + g.nextInt(0, (int) horizon + 1);
            long start = STARTS[g.nextInt(STARTS.length)];
            long length = LENGTHS[g.nextInt(LENGTHS.length)];
            stays.add(booking(day, start, start + length,
                    pick(g, spellings, BAD_BOOKING_DOCTORS, 5)));
        }
        if (g.nextInt(100) < 15) {
            long day = requestedDay + g.nextInt(0, (int) horizon + 1);
            stays.addAll(spans(day, NAMES[0], 540, 560, 580, 600));
        }
        if (g.nextInt(100) < 12) {
            long day = requestedDay + g.nextInt(0, (int) horizon + 1);
            stays.add(booking(day, 800, 820, "Ada"));
            stays.add(booking(day, 820, 845, "Ada"));
            stays.add(booking(day, 845, 870, "Ada"));
        }
        if (g.nextInt(100) < 3) stays.add(badBooking(g, requestedDay));
        if (g.nextInt(400) == 0) {
            stays.clear();
            for (int index = 0; index < 201; index++) stays.add(booking(500 + index, 0, 1, "Ada"));
        }
        spec.bookings(stays);

        if (g.nextInt(500) == 0) spec.horizon(15);
        if (g.nextInt(700) == 0) spec.nowMinute(1440);
        if (g.nextInt(900) == 0) spec.nowDay(1_000_001);
        if (g.nextInt(900) == 0) spec.requested(1_000_001);
        if (g.nextInt(200) == 0) spec.requested(nowDay - 1 - g.nextInt(4));
        return spec.done();
    }

    static void randomCases() {
        SplittableRandom g = new SplittableRandom(20261017);
        TreeMap<String, Integer> errors = new TreeMap<>();
        Set<String> kinds = new TreeSet<>();
        Set<Boolean> urgency = new TreeSet<>();
        Set<String> doctors = new TreeSet<>();
        Set<Long> offsets = new TreeSet<>();
        int valid = 0;
        for (int round = 0; round < 2000; round++) {
            solution.Request request = randomRequest(g);
            Object expected = oracle(request);
            Object actual = solution.solution(request);
            if (!expected.equals(actual)) {
                throw new AssertionError("round " + round + " expected=" + expected
                        + " actual=" + actual + " " + request);
            }
            if (expected instanceof solution.Appointment found) {
                valid++;
                kinds.add(request.kind().strip().toLowerCase(Locale.ROOT));
                urgency.add(request.urgent());
                doctors.add(found.doctor());
                offsets.add(found.day() - request.requestedDay());
            } else {
                errors.merge(((solution.ClinicError) expected).code(), 1, Integer::sum);
            }
        }
        if (valid * 2 < 2000) throw new AssertionError("random mix valid=" + valid + " under half");
        if (!kinds.containsAll(List.of("checkup", "consultation", "procedure"))) {
            throw new AssertionError("random kinds too narrow: " + kinds);
        }
        if (urgency.size() != 2 || doctors.size() < 2 || !offsets.contains(0L)) {
            throw new AssertionError("random mix too narrow: urgency=" + urgency + " doctors="
                    + doctors + " offsets=" + offsets);
        }
        for (String code : List.of("BAD_REQUEST", "BAD_DOCTORS", "BAD_WINDOW", "BAD_HOLIDAY",
                "BAD_BOOKING", "UNKNOWN_DOCTOR", "BAD_DAY_ORDER", "NO_SLOT")) {
            if (!errors.containsKey(code)) {
                throw new AssertionError("random loop never produced " + code + ": " + errors);
            }
        }
        System.out.println("random requests=2000 valid=" + valid + " invalid=" + (2000 - valid)
                + " kinds=" + kinds + " doctors=" + doctors + " dayOffsets=" + offsets
                + " errors=" + errors);
    }
}
