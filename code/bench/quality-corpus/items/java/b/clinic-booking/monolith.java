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

    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9 -]+");

    /** Return the earliest valid appointment or the first validation error. */
    public static Object solution(Request request) {
        String kind = request.kind().strip().toLowerCase(Locale.ROOT);
        String preferredName = request.preferredDoctor().strip();
        String preferredKey = null;
        if (!preferredName.isEmpty() && NAME.matcher(preferredName).matches()) {
            preferredKey = preferredName.toLowerCase(Locale.ROOT);
        }

        List<String> doctorNames = new ArrayList<>();
        List<String> doctorKeys = new ArrayList<>();
        List<List<Window>> doctorWindows = new ArrayList<>();
        for (Doctor doctor : request.doctors()) {
            String trimmedName = doctor.name().strip();
            boolean nameUsable = !trimmedName.isEmpty() && NAME.matcher(trimmedName).matches();
            if (nameUsable) {
                doctorKeys.add(trimmedName.toLowerCase(Locale.ROOT));
            } else {
                doctorKeys.add(null);
            }
            doctorNames.add(trimmedName);
            doctorWindows.add(doctor.windows());
        }

        List<Long> bookingDays = new ArrayList<>();
        List<Long> bookingStarts = new ArrayList<>();
        List<Long> bookingEnds = new ArrayList<>();
        List<String> bookingKeys = new ArrayList<>();
        for (Booking booking : request.bookings()) {
            String bookedName = booking.doctor().strip();
            boolean nameUsable = !bookedName.isEmpty() && NAME.matcher(bookedName).matches();
            if (nameUsable) {
                bookingKeys.add(bookedName.toLowerCase(Locale.ROOT));
            } else {
                bookingKeys.add(null);
            }
            bookingDays.add(booking.day());
            bookingStarts.add(booking.start());
            bookingEnds.add(booking.end());
        }

        if (request.nowDay() < 0) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.nowDay() > 1_000_000) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.requestedDay() < 0) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.requestedDay() > 1_000_000) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.nowMinute() < 0 || request.nowMinute() > 1439) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.horizonDays() < 0) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (request.horizonDays() > 14) {
            return new ClinicError("BAD_REQUEST", null);
        }
        if (!kind.equals("checkup") && !kind.equals("consultation") && !kind.equals("procedure")) {
            return new ClinicError("BAD_REQUEST", null);
        }

        if (doctorNames.isEmpty() || doctorNames.size() > 12) {
            return new ClinicError("BAD_DOCTORS", null);
        }
        Set<String> knownKeys = new HashSet<>();
        for (int index = 0; index < doctorNames.size(); index++) {
            String key = doctorKeys.get(index);
            if (key == null) {
                return new ClinicError("BAD_DOCTORS", index);
            }
            if (!knownKeys.add(key)) {
                return new ClinicError("BAD_DOCTORS", index);
            }
        }

        for (int index = 0; index < doctorWindows.size(); index++) {
            List<Window> windows = doctorWindows.get(index);
            if (windows.size() > 8) {
                return new ClinicError("BAD_WINDOW", index);
            }
            for (Window window : windows) {
                if (window.weekday() < 0 || window.weekday() > 6) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                if (window.open() < 0) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                if (window.close() > 1440) {
                    return new ClinicError("BAD_WINDOW", index);
                }
                if (window.open() >= window.close()) {
                    return new ClinicError("BAD_WINDOW", index);
                }
            }
        }

        List<Long> holidays = request.holidays();
        if (holidays.size() > 60) {
            return new ClinicError("BAD_HOLIDAY", null);
        }
        Set<Long> holidaySet = new HashSet<>();
        for (int index = 0; index < holidays.size(); index++) {
            long holiday = holidays.get(index);
            if (holiday < 0 || holiday > 1_000_000) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
            if (!holidaySet.add(holiday)) {
                return new ClinicError("BAD_HOLIDAY", index);
            }
        }

        if (bookingDays.size() > 200) {
            return new ClinicError("BAD_BOOKING", null);
        }
        for (int index = 0; index < bookingDays.size(); index++) {
            long bookedDay = bookingDays.get(index);
            if (bookedDay < 0 || bookedDay > 1_000_000) {
                return new ClinicError("BAD_BOOKING", index);
            }
            long bookedStart = bookingStarts.get(index);
            long bookedEnd = bookingEnds.get(index);
            if (bookedStart < 0) {
                return new ClinicError("BAD_BOOKING", index);
            }
            if (bookedStart >= bookedEnd) {
                return new ClinicError("BAD_BOOKING", index);
            }
            if (bookedEnd > 1440) {
                return new ClinicError("BAD_BOOKING", index);
            }
            if (!knownKeys.contains(bookingKeys.get(index))) {
                return new ClinicError("BAD_BOOKING", index);
            }
        }

        if (!preferredName.isEmpty() && !knownKeys.contains(preferredKey)) {
            return new ClinicError("UNKNOWN_DOCTOR", null);
        }
        if (request.requestedDay() < request.nowDay()) {
            return new ClinicError("BAD_DAY_ORDER", null);
        }
        if (request.requestedDay() > request.nowDay() + 8) {
            return new ClinicError("BAD_DAY_ORDER", null);
        }

        long duration;
        long buffer;
        if (kind.equals("checkup")) {
            duration = 20;
            buffer = 5;
        } else if (kind.equals("consultation")) {
            duration = 30;
            buffer = 10;
        } else {
            duration = 60;
            buffer = 15;
        }

        List<Integer> candidates = new ArrayList<>();
        for (int index = 0; index < doctorKeys.size(); index++) {
            boolean preferredOnly = !request.urgent() && !preferredName.isEmpty();
            if (preferredOnly && !doctorKeys.get(index).equals(preferredKey)) {
                continue;
            }
            candidates.add(index);
        }
        candidates.sort(Comparator.comparing(doctorKeys::get));

        long firstDay = request.requestedDay();
        long horizonLimit = firstDay + request.horizonDays();
        long contractLimit = firstDay + 14;
        long dayLimit = Math.min(horizonLimit, contractLimit);
        long lastDay = Math.min(dayLimit, 1_000_000);
        List<Long> candidateDays = new ArrayList<>();
        for (long day = firstDay; day <= lastDay; day++) {
            if (holidaySet.contains(day)) {
                continue;
            }
            candidateDays.add(day);
        }

        Map<Long, List<Integer>> bookingsByDay = new HashMap<>();
        for (int index = 0; index < bookingDays.size(); index++) {
            long bookedDay = bookingDays.get(index);
            List<Integer> dayList = bookingsByDay.get(bookedDay);
            if (dayList == null) {
                dayList = new ArrayList<>();
                bookingsByDay.put(bookedDay, dayList);
            }
            dayList.add(index);
        }

        List<String> trace = List.of("normalised", "validated", "holiday-filter",
                "hours-and-lunch", "notice", "doctor-availability", "daily-cap",
                "booking-conflicts", "urgent-priority", "earliest-grid-slot");
        long minimumStartToday = request.nowMinute() + 60;
        for (long day : candidateDays) {
            long weekday = day % 7;
            long openingStart;
            long openingEnd;
            if (weekday < 5) {
                openingStart = 540;
                openingEnd = 1020;
            } else if (weekday == 5) {
                openingStart = 600;
                openingEnd = 840;
            } else {
                openingStart = 0;
                openingEnd = 0;
            }
            Map<String, List<Integer>> takenByKey = new HashMap<>();
            for (int other : bookingsByDay.getOrDefault(day, List.of())) {
                String otherKey = bookingKeys.get(other);
                List<Integer> bucket = takenByKey.get(otherKey);
                if (bucket == null) {
                    bucket = new ArrayList<>();
                    takenByKey.put(otherKey, bucket);
                }
                bucket.add(other);
            }
            for (long start = 0; start <= 1435; start += 5) {
                long reservedEnd = start + duration + buffer;
                boolean insideOpening = start >= openingStart && reservedEnd <= openingEnd;
                if (!insideOpening) {
                    continue;
                }
                boolean overlapsLunch = start < 780 && reservedEnd > 720;
                if (overlapsLunch) {
                    continue;
                }
                boolean noticed = day > request.nowDay() || start >= minimumStartToday;
                if (!noticed) {
                    continue;
                }
                for (int index : candidates) {
                    String candidateKey = doctorKeys.get(index);
                    List<Integer> taken = takenByKey.getOrDefault(candidateKey, List.of());
                    if (taken.size() >= 4) {
                        continue;
                    }
                    List<Window> weekdayWindows = new ArrayList<>();
                    for (Window window : doctorWindows.get(index)) {
                        if (window.weekday() == weekday) {
                            weekdayWindows.add(window);
                        }
                    }
                    boolean insideWindow = false;
                    for (Window window : weekdayWindows) {
                        if (window.open() <= start && reservedEnd <= window.close()) {
                            insideWindow = true;
                        }
                    }
                    if (!insideWindow) {
                        continue;
                    }
                    boolean conflicting = false;
                    for (int other : taken) {
                        boolean beforeBooking = reservedEnd <= bookingStarts.get(other);
                        boolean afterBooking = start >= bookingEnds.get(other);
                        if (!beforeBooking && !afterBooking) {
                            conflicting = true;
                        }
                    }
                    if (conflicting) {
                        continue;
                    }
                    long appointmentEnd = start + duration;
                    return new Appointment(day, start, appointmentEnd, doctorNames.get(index),
                            trace);
                }
            }
        }
        return new ClinicError("NO_SLOT", null);
    }
}
