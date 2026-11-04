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

    record Timing(long duration, long buffer) {}

    record Slot(long day, long start, long end, String key, String name) {}

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
        String kind = request.kind().strip().toLowerCase(Locale.ROOT);
        String preferredName = request.preferredDoctor().strip();
        String preferredKey = preferredName.isEmpty() || !NAME.matcher(preferredName).matches()
                ? null : preferredName.toLowerCase(Locale.ROOT);

        List<NormalDoctor> doctors = new ArrayList<>();
        for (Doctor doctor : request.doctors()) {
            String name = doctor.name().strip();
            String key = name.isEmpty() || !NAME.matcher(name).matches()
                    ? null : name.toLowerCase(Locale.ROOT);
            doctors.add(new NormalDoctor(name, key, doctor.windows()));
        }
        List<NormalBooking> bookings = new ArrayList<>();
        for (Booking booking : request.bookings()) {
            String name = booking.doctor().strip();
            String key = name.isEmpty() || !NAME.matcher(name).matches()
                    ? null : name.toLowerCase(Locale.ROOT);
            bookings.add(new NormalBooking(booking.day(), booking.start(), booking.end(), key));
        }

        boolean nowDayValid = request.nowDay() >= 0 && request.nowDay() <= 1_000_000;
        boolean requestedDayValid = request.requestedDay() >= 0
                && request.requestedDay() <= 1_000_000;
        if (!nowDayValid || !requestedDayValid) {
            return new ClinicError("BAD_REQUEST", null);
        }
        boolean nowMinuteValid = request.nowMinute() >= 0 && request.nowMinute() <= 1439;
        boolean horizonValid = request.horizonDays() >= 0 && request.horizonDays() <= 14;
        if (!nowMinuteValid || !horizonValid || !TIMINGS.containsKey(kind)) {
            return new ClinicError("BAD_REQUEST", null);
        }

        if (doctors.isEmpty() || doctors.size() > 12) {
            return new ClinicError("BAD_DOCTORS", null);
        }
        Set<String> keys = new HashSet<>();
        for (int index = 0; index < doctors.size(); index++) {
            String key = doctors.get(index).key();
            if (key == null) {
                return new ClinicError("BAD_DOCTORS", index);
            }
            if (!keys.add(key)) {
                return new ClinicError("BAD_DOCTORS", index);
            }
        }

        for (int index = 0; index < doctors.size(); index++) {
            List<Window> windows = doctors.get(index).windows();
            if (windows.size() > 8) {
                return new ClinicError("BAD_WINDOW", index);
            }
            for (Window window : windows) {
                boolean weekdayValid = window.weekday() >= 0 && window.weekday() <= 6;
                if (!weekdayValid) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                boolean openValid = window.open() >= 0;
                if (!openValid) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                boolean closeValid = window.close() <= 1440;
                if (!closeValid) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                boolean ordered = window.open() < window.close();
                if (!ordered) {
                    return new ClinicError("BAD_WINDOW", index);
                }
            }
        }

        List<Long> holidayList = request.holidays();
        if (holidayList.size() > 60) {
            return new ClinicError("BAD_HOLIDAY", null);
        }
        Set<Long> holidaySet = new HashSet<>();
        for (int index = 0; index < holidayList.size(); index++) {
            long holiday = holidayList.get(index);
            boolean dayValid = holiday >= 0 && holiday <= 1_000_000;
            if (!dayValid) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
            if (!holidaySet.add(holiday)) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
        }

        if (bookings.size() > 200) {
            return new ClinicError("BAD_BOOKING", null);
        }
        for (int index = 0; index < bookings.size(); index++) {
            NormalBooking booking = bookings.get(index);
            boolean dayValid = booking.day() >= 0 && booking.day() <= 1_000_000;
            if (!dayValid) {
                return new ClinicError("BAD_BOOKING", index);
            }
            boolean startValid = booking.start() >= 0;
            if (!startValid) {
                return new ClinicError("BAD_BOOKING", index);
            }
            boolean endValid = booking.start() < booking.end() && booking.end() <= 1440;
            if (!endValid) {
                return new ClinicError("BAD_BOOKING", index);
            }
            boolean doctorKnown = keys.contains(booking.key());
            if (!doctorKnown) {
                return new ClinicError("BAD_BOOKING", index);
            }
        }

        boolean preferredKnown = preferredName.isEmpty() || keys.contains(preferredKey);
        if (!preferredKnown) {
            return new ClinicError("UNKNOWN_DOCTOR", null);
        }
        boolean dayNotPast = request.requestedDay() >= request.nowDay();
        if (!dayNotPast) {
            return new ClinicError("BAD_DAY_ORDER", null);
        }
        boolean dayWithinNotice = request.requestedDay() <= request.nowDay() + 8;
        if (!dayWithinNotice) {
            return new ClinicError("BAD_DAY_ORDER", null);
        }

        Timing timing = TIMINGS.get(kind);
        long duration = timing.duration();
        long buffer = timing.buffer();
        long reservedLength = duration + buffer;

        List<NormalDoctor> panel = new ArrayList<>();
        if (!request.urgent() && !preferredName.isEmpty()) {
            for (NormalDoctor doctor : doctors) {
                if (doctor.key().equals(preferredKey)) {
                    panel.add(doctor);
                }
            }
        } else {
            panel.addAll(doctors);
        }
        panel.sort(Comparator.comparing(NormalDoctor::key));

        List<Long> gridStarts = new ArrayList<>();
        for (long start = 0; start <= 1435; start += 5) {
            gridStarts.add(start);
        }

        long firstDay = request.requestedDay();
        long horizonEnd = firstDay + request.horizonDays();
        long contractEnd = firstDay + 14;
        long lastDay = Math.min(Math.min(horizonEnd, contractEnd), 1_000_000);
        List<Long> candidateDays = new ArrayList<>();
        for (long day = firstDay; day <= lastDay; day++) {
            if (!holidaySet.contains(day)) {
                candidateDays.add(day);
            }
        }

        List<Slot> slots = new ArrayList<>();
        for (long day : candidateDays) {
            long weekday = day % 7;
            long[] opening = OPENINGS[(int) weekday];
            Map<String, List<NormalBooking>> takenToday = new HashMap<>();
            for (NormalBooking booking : bookings) {
                if (booking.day() != day) {
                    continue;
                }
                List<NormalBooking> doctorBookings = takenToday.get(booking.key());
                if (doctorBookings == null) {
                    doctorBookings = new ArrayList<>();
                    takenToday.put(booking.key(), doctorBookings);
                }
                doctorBookings.add(booking);
            }
            for (long start : gridStarts) {
                long reservedEnd = start + reservedLength;
                long appointmentEnd = start + duration;
                boolean noticed = day > request.nowDay() || start >= request.nowMinute() + 60;
                if (!noticed) {
                    continue;
                }
                boolean insideOpening = opening[0] <= start && reservedEnd <= opening[1];
                if (!insideOpening) {
                    continue;
                }
                boolean missesLunch = start >= 780 || reservedEnd <= 720;
                if (!missesLunch) {
                    continue;
                }
                for (NormalDoctor doctor : panel) {
                    boolean windowFits = false;
                    for (Window window : doctor.windows()) {
                        boolean matchingWeekday = window.weekday() == weekday;
                        boolean contained = window.open() <= start
                                && reservedEnd <= window.close();
                        windowFits = windowFits || (matchingWeekday && contained);
                    }
                    if (!windowFits) {
                        continue;
                    }
                    List<NormalBooking> taken = takenToday.getOrDefault(doctor.key(), List.of());
                    boolean underCap = taken.size() < 4;
                    if (!underCap) {
                        continue;
                    }
                    boolean overlaps = false;
                    for (NormalBooking booking : taken) {
                        boolean clear = start >= booking.end() || reservedEnd <= booking.start();
                        if (!clear) {
                            overlaps = true;
                        }
                    }
                    if (overlaps) {
                        continue;
                    }
                    slots.add(new Slot(day, start, appointmentEnd, doctor.key(), doctor.name()));
                }
            }
        }

        if (slots.isEmpty()) {
            return new ClinicError("NO_SLOT", null);
        }
        slots.sort(Comparator.comparingLong(Slot::day).thenComparingLong(Slot::start)
                .thenComparing(Slot::key));
        Slot chosen = slots.get(0);
        return new Appointment(chosen.day(), chosen.start(), chosen.end(), chosen.name(), TRACE);
    }
}
