package corpus

import (
	"regexp"
	"sort"
	"strings"
)

type Window struct {
	Weekday int
	Open    int
	Close   int
}
type Doctor struct {
	Name    string
	Windows []Window
}
type Booking struct {
	Day    int
	Start  int
	End    int
	Doctor string
}
type Request struct {
	NowDay          int
	NowMinute       int
	RequestedDay    int
	HorizonDays     int
	Kind            string
	Urgent          bool
	PreferredDoctor string
	Holidays        []int
	Doctors         []Doctor
	Bookings        []Booking
}
type Appointment struct {
	Day    int
	Start  int
	End    int
	Doctor string
	Trace  []string
}
type ClinicError struct {
	Code  string
	Index *int
}
type Outcome struct {
	Appointment *Appointment
	Err         *ClinicError
}
type kindRule struct{ duration, buffer int }

const (
	maxDay        = 1_000_000
	horizonLimit  = 14
	dailyCap      = 4
	noticeMinutes = 60
	lunchStart    = 720
	lunchEnd      = 780
)

var nameRule = regexp.MustCompile(`^[A-Za-z0-9 -]+$`)
var kindRules = map[string]kindRule{
	"checkup":      {20, 5},
	"consultation": {30, 10},
	"procedure":    {60, 15},
}
var openingHours = [7][2]int{
	{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
	{600, 840}, {0, 0},
}

// Solution returns the earliest valid appointment or the first validation error.
func Solution(request Request) Outcome {
	doctors := make([]Doctor, len(request.Doctors))
	doctorKeys := make([]string, len(request.Doctors))
	for index, doctor := range request.Doctors {
		name := strings.Trim(doctor.Name, " ")
		nameIsValid := nameRule.MatchString(name)
		key := ""
		if nameIsValid {
			key = strings.ToLower(name)
		}
		doctors[index] = Doctor{Name: name, Windows: doctor.Windows}
		doctorKeys[index] = key
	}
	bookings := make([]Booking, len(request.Bookings))
	bookingKeys := make([]string, len(request.Bookings))
	for index, booking := range request.Bookings {
		name := strings.Trim(booking.Doctor, " ")
		nameIsValid := nameRule.MatchString(name)
		key := ""
		if nameIsValid {
			key = strings.ToLower(name)
		}
		cleaned := Booking{
			Day: booking.Day, Start: booking.Start, End: booking.End, Doctor: name,
		}
		bookings[index] = cleaned
		bookingKeys[index] = key
	}
	preferred := strings.Trim(request.PreferredDoctor, " ")
	preferredKey := ""
	preferenceIsNamed := nameRule.MatchString(preferred)
	if preferenceIsNamed {
		preferredKey = strings.ToLower(preferred)
	}
	known := make(map[string]bool, len(doctorKeys))
	for _, key := range doctorKeys {
		nameIsUsable := key != ""
		if nameIsUsable {
			known[key] = true
		}
	}
	kind := strings.ToLower(strings.Trim(request.Kind, " "))
	settings, kindIsKnown := kindRules[kind]
	nowDay := request.NowDay
	nowMinute := request.NowMinute
	requestedDay := request.RequestedDay
	horizon := request.HorizonDays
	nowDayIsValid := nowDay >= 0 && nowDay <= maxDay
	if !nowDayIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	requestedDayIsValid := requestedDay >= 0 && requestedDay <= maxDay
	if !requestedDayIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	nowMinuteIsValid := nowMinute >= 0 && nowMinute <= 1439
	if !nowMinuteIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	horizonIsValid := horizon >= 0 && horizon <= horizonLimit
	if !horizonIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if !kindIsKnown {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	doctorCount := len(doctorKeys)
	countIsAtLeastOne := doctorCount >= 1
	countIsAtMostTwelve := doctorCount <= 12
	doctorCountIsValid := countIsAtLeastOne && countIsAtMostTwelve
	if !doctorCountIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_DOCTORS"}}
	}
	seenNames := make(map[string]bool, doctorCount)
	for index, key := range doctorKeys {
		keyIsEmpty := key == ""
		keyIsRepeated := seenNames[key]
		nameIsUnique := !keyIsEmpty && !keyIsRepeated
		if !nameIsUnique {
			position := index
			return Outcome{Err: &ClinicError{Code: "BAD_DOCTORS", Index: &position}}
		}
		seenNames[key] = true
	}
	for index, doctor := range doctors {
		windowCount := len(doctor.Windows)
		windowCountIsValid := windowCount <= 8
		if !windowCountIsValid {
			position := index
			return Outcome{Err: &ClinicError{Code: "BAD_WINDOW", Index: &position}}
		}
		for _, window := range doctor.Windows {
			weekdayIsValid := window.Weekday >= 0 && window.Weekday <= 6
			openIsNonNegative := window.Open >= 0
			openBeforeClose := window.Open < window.Close
			openingIsValid := openIsNonNegative && openBeforeClose
			closingIsValid := window.Close <= 1440
			windowIsValid := weekdayIsValid && openingIsValid && closingIsValid
			if !windowIsValid {
				position := index
				problem := &ClinicError{Code: "BAD_WINDOW", Index: &position}
				return Outcome{Err: problem}
			}
		}
	}
	holidayCount := len(request.Holidays)
	holidayListIsTooLong := holidayCount > 60
	if holidayListIsTooLong {
		return Outcome{Err: &ClinicError{Code: "BAD_HOLIDAY"}}
	}
	closedDays := make(map[int]bool, holidayCount)
	for index, day := range request.Holidays {
		dayIsInRange := day >= 0 && day <= maxDay
		dayIsRepeated := closedDays[day]
		holidayIsValid := dayIsInRange && !dayIsRepeated
		if !holidayIsValid {
			position := index
			return Outcome{Err: &ClinicError{Code: "BAD_HOLIDAY", Index: &position}}
		}
		closedDays[day] = true
	}
	bookingCount := len(bookings)
	bookingListIsTooLong := bookingCount > 200
	if bookingListIsTooLong {
		return Outcome{Err: &ClinicError{Code: "BAD_BOOKING"}}
	}
	for index, booking := range bookings {
		bookedDayIsValid := booking.Day >= 0 && booking.Day <= maxDay
		startIsValid := booking.Start >= 0
		startBeforeEnd := booking.Start < booking.End
		endWithinDay := booking.End <= 1440
		spanIsValid := startBeforeEnd && endWithinDay
		bookingKey := bookingKeys[index]
		keyIsListed := bookingKey != ""
		doctorIsKnown := keyIsListed && known[bookingKey]
		bookingFieldsAreValid := bookedDayIsValid && startIsValid && spanIsValid
		bookingIsValid := bookingFieldsAreValid && doctorIsKnown
		if !bookingIsValid {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
	}
	preferenceIsAbsent := preferred == ""
	preferredIsKnown := preferenceIsAbsent || known[preferredKey]
	if !preferredIsKnown {
		return Outcome{Err: &ClinicError{Code: "UNKNOWN_DOCTOR"}}
	}
	gap := requestedDay - nowDay
	gapIsValid := gap >= 0 && gap <= 8
	if !gapIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_DAY_ORDER"}}
	}
	restrictedToPreferred := !request.Urgent && !preferenceIsAbsent
	eligible := make([]int, 0, doctorCount)
	for index := range doctors {
		preferenceExcludes := restrictedToPreferred && doctorKeys[index] != preferredKey
		if preferenceExcludes {
			continue
		}
		eligible = append(eligible, index)
	}
	sort.Slice(eligible, func(left, right int) bool {
		leftKey := doctorKeys[eligible[left]]
		rightKey := doctorKeys[eligible[right]]
		return leftKey < rightKey
	})
	firstDay := requestedDay
	lastDay := requestedDay + horizon
	lastDayExceedsLimit := lastDay > maxDay
	if lastDayExceedsLimit {
		lastDay = maxDay
	}
	candidateDays := make([]int, 0, lastDay-firstDay+1)
	for day := firstDay; day <= lastDay; day++ {
		dayIsClosed := closedDays[day]
		if dayIsClosed {
			continue
		}
		candidateDays = append(candidateDays, day)
	}
	duration := settings.duration
	buffer := settings.buffer
	reservedLength := duration + buffer
	for _, day := range candidateDays {
		weekday := day % 7
		hours := openingHours[weekday]
		opensAt := hours[0]
		shutsAt := hours[1]
		for start := 0; start <= 1435; start += 5 {
			appointmentEnd := start + duration
			reservedEnd := start + reservedLength
			opensEarlyEnough := start >= opensAt
			closesLateEnough := reservedEnd <= shutsAt
			insideOpeningHours := opensEarlyEnough && closesLateEnough
			if !insideOpeningHours {
				continue
			}
			endsBeforeLunch := reservedEnd <= lunchStart
			startsAfterLunch := start >= lunchEnd
			clearsLunch := endsBeforeLunch || startsAfterLunch
			if !clearsLunch {
				continue
			}
			noticeThreshold := nowMinute + noticeMinutes
			sameDay := day == nowDay
			noticeIsMet := !sameDay || start >= noticeThreshold
			if !noticeIsMet {
				continue
			}
			for _, index := range eligible {
				doctor := doctors[index]
				key := doctorKeys[index]
				covered := false
				for _, window := range doctor.Windows {
					fitsWeekday := window.Weekday == weekday
					startsEarlyEnough := window.Open <= start
					endsLateEnough := reservedEnd <= window.Close
					windowCovers := fitsWeekday && startsEarlyEnough
					windowCovers = windowCovers && endsLateEnough
					if windowCovers {
						covered = true
						break
					}
				}
				if !covered {
					continue
				}
				dailyCount := 0
				bookingOverlaps := false
				for bookingIndex, booking := range bookings {
					sameBookingDay := booking.Day == day
					sameDoctor := bookingKeys[bookingIndex] == key
					sameSlot := sameBookingDay && sameDoctor
					if !sameSlot {
						continue
					}
					dailyCount++
					overlapStartsEarly := start < booking.End
					overlapEndsLate := booking.Start < reservedEnd
					if overlapStartsEarly && overlapEndsLate {
						bookingOverlaps = true
					}
				}
				capReached := dailyCount >= dailyCap
				slotIsTaken := bookingOverlaps || capReached
				if slotIsTaken {
					continue
				}
				trace := make([]string, 0, 10)
				trace = append(trace, "normalised", "validated")
				trace = append(trace, "holiday-filter", "hours-and-lunch")
				trace = append(trace, "notice", "doctor-availability")
				trace = append(trace, "daily-cap", "booking-conflicts")
				trace = append(trace, "urgent-priority", "earliest-grid-slot")
				return Outcome{Appointment: &Appointment{
					Day: day, Start: start, End: appointmentEnd,
					Doctor: doctor.Name, Trace: trace,
				}}
			}
		}
	}
	noSlot := &ClinicError{Code: "NO_SLOT"}
	return Outcome{Err: noSlot}
}
