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
		trimmedName := strings.Trim(doctor.Name, " ")
		nameIsValid := nameRule.MatchString(trimmedName)
		key := ""
		if nameIsValid {
			loweredName := strings.ToLower(trimmedName)
			key = loweredName
		}
		cleaned := Doctor{Name: trimmedName, Windows: doctor.Windows}
		doctors[index] = cleaned
		doctorKeys[index] = key
	}
	bookings := make([]Booking, len(request.Bookings))
	bookingKeys := make([]string, len(request.Bookings))
	for index, booking := range request.Bookings {
		trimmedName := strings.Trim(booking.Doctor, " ")
		nameIsValid := nameRule.MatchString(trimmedName)
		key := ""
		if nameIsValid {
			loweredName := strings.ToLower(trimmedName)
			key = loweredName
		}
		cleaned := Booking{
			Day:    booking.Day,
			Start:  booking.Start,
			End:    booking.End,
			Doctor: trimmedName,
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
	knownNames := make(map[string]bool, len(doctorKeys))
	for _, key := range doctorKeys {
		nameIsUsable := key != ""
		if nameIsUsable {
			knownNames[key] = true
		}
	}
	kind := strings.ToLower(strings.Trim(request.Kind, " "))
	kindSettings, kindIsKnown := kindRules[kind]
	nowDay := request.NowDay
	nowMinute := request.NowMinute
	requestedDay := request.RequestedDay
	horizon := request.HorizonDays
	if nowDay < 0 {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if nowDay > maxDay {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if requestedDay < 0 {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if requestedDay > maxDay {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if nowMinute < 0 {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if nowMinute > 1439 {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if horizon < 0 {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if horizon > horizonLimit {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	if !kindIsKnown {
		return Outcome{Err: &ClinicError{Code: "BAD_REQUEST"}}
	}
	doctorCount := len(doctors)
	doctorCountIsValid := doctorCount >= 1 && doctorCount <= 12
	if !doctorCountIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_DOCTORS"}}
	}
	for index, key := range doctorKeys {
		if key == "" {
			position := index
			problem := &ClinicError{Code: "BAD_DOCTORS", Index: &position}
			return Outcome{Err: problem}
		}
		repeated := false
		for earlier := 0; earlier < index; earlier++ {
			if doctorKeys[earlier] == key {
				repeated = true
				break
			}
		}
		if repeated {
			position := index
			problem := &ClinicError{Code: "BAD_DOCTORS", Index: &position}
			return Outcome{Err: problem}
		}
	}
	for index, doctor := range doctors {
		windowCount := len(doctor.Windows)
		windowCountIsValid := windowCount <= 8
		if !windowCountIsValid {
			position := index
			problem := &ClinicError{Code: "BAD_WINDOW", Index: &position}
			return Outcome{Err: problem}
		}
		for _, window := range doctor.Windows {
			weekdayIsValid := window.Weekday >= 0 && window.Weekday <= 6
			if !weekdayIsValid {
				position := index
				problem := &ClinicError{Code: "BAD_WINDOW", Index: &position}
				return Outcome{Err: problem}
			}
			openIsValid := window.Open >= 0 && window.Open < window.Close
			if !openIsValid {
				position := index
				problem := &ClinicError{Code: "BAD_WINDOW", Index: &position}
				return Outcome{Err: problem}
			}
			if window.Close > 1440 {
				position := index
				problem := &ClinicError{Code: "BAD_WINDOW", Index: &position}
				return Outcome{Err: problem}
			}
		}
	}
	holidayCount := len(request.Holidays)
	holidayCountIsValid := holidayCount <= 60
	if !holidayCountIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_HOLIDAY"}}
	}
	seenHolidays := make(map[int]bool, holidayCount)
	for index, day := range request.Holidays {
		if day < 0 || day > maxDay {
			position := index
			problem := &ClinicError{Code: "BAD_HOLIDAY", Index: &position}
			return Outcome{Err: problem}
		}
		if seenHolidays[day] {
			position := index
			problem := &ClinicError{Code: "BAD_HOLIDAY", Index: &position}
			return Outcome{Err: problem}
		}
		seenHolidays[day] = true
	}
	bookingCount := len(bookings)
	bookingCountIsValid := bookingCount <= 200
	if !bookingCountIsValid {
		return Outcome{Err: &ClinicError{Code: "BAD_BOOKING"}}
	}
	for index, booking := range bookings {
		if booking.Day < 0 {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
		if booking.Day > maxDay {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
		if booking.Start < 0 {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
		spansTime := booking.Start < booking.End
		endsWithinDay := booking.End <= 1440
		spanIsValid := spansTime && endsWithinDay
		if !spanIsValid {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
		key := bookingKeys[index]
		doctorIsListed := false
		for _, listed := range doctorKeys {
			if listed == key {
				doctorIsListed = true
				break
			}
		}
		doctorIsKnown := key != "" && doctorIsListed
		if !doctorIsKnown {
			position := index
			problem := &ClinicError{Code: "BAD_BOOKING", Index: &position}
			return Outcome{Err: problem}
		}
	}
	if preferred != "" && !knownNames[preferredKey] {
		return Outcome{Err: &ClinicError{Code: "UNKNOWN_DOCTOR"}}
	}
	if requestedDay < nowDay {
		return Outcome{Err: &ClinicError{Code: "BAD_DAY_ORDER"}}
	}
	if requestedDay-nowDay > 8 {
		return Outcome{Err: &ClinicError{Code: "BAD_DAY_ORDER"}}
	}
	onlyPreferred := !request.Urgent && preferred != ""
	eligible := make([]int, 0, doctorCount)
	for index := range doctors {
		key := doctorKeys[index]
		preferenceExcludes := onlyPreferred && key != preferredKey
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
	lastDay := requestedDay + horizon
	if lastDay > maxDay {
		lastDay = maxDay
	}
	openDays := make([]int, 0, lastDay-requestedDay+1)
	for day := requestedDay; day <= lastDay; day++ {
		if seenHolidays[day] {
			continue
		}
		openDays = append(openDays, day)
	}
	duration := kindSettings.duration
	buffer := kindSettings.buffer
	for _, day := range openDays {
		weekday := day % 7
		hours := openingHours[weekday]
		opensAt := hours[0]
		shutsAt := hours[1]
		for start := 0; start <= 1435; start += 5 {
			appointmentEnd := start + duration
			reservedEnd := appointmentEnd + buffer
			for _, index := range eligible {
				doctor := doctors[index]
				key := doctorKeys[index]
				opensEarlyEnough := start >= opensAt
				closesLateEnough := reservedEnd <= shutsAt
				insideOpeningHours := opensEarlyEnough && closesLateEnough
				if !insideOpeningHours {
					continue
				}
				clearsLunch := reservedEnd <= lunchStart || start >= lunchEnd
				if !clearsLunch {
					continue
				}
				windowCovers := false
				for _, window := range doctor.Windows {
					if window.Weekday != weekday {
						continue
					}
					if window.Open > start {
						continue
					}
					if reservedEnd > window.Close {
						continue
					}
					windowCovers = true
					break
				}
				if !windowCovers {
					continue
				}
				noticeThreshold := nowMinute + noticeMinutes
				if day == nowDay {
					if start < noticeThreshold {
						continue
					}
				}
				dailyCount := 0
				bookingOverlaps := false
				for bookingIndex, booking := range bookings {
					if booking.Day != day {
						continue
					}
					if bookingKeys[bookingIndex] != key {
						continue
					}
					dailyCount++
					if start < booking.End {
						if booking.Start < reservedEnd {
							bookingOverlaps = true
							break
						}
					}
				}
				if bookingOverlaps {
					continue
				}
				if dailyCount >= dailyCap {
					continue
				}
				trace := make([]string, 0, 10)
				trace = append(trace, "normalised", "validated")
				trace = append(trace, "holiday-filter")
				trace = append(trace, "hours-and-lunch", "notice")
				trace = append(trace, "doctor-availability")
				trace = append(trace, "daily-cap", "booking-conflicts")
				trace = append(trace, "urgent-priority")
				trace = append(trace, "earliest-grid-slot")
				found := &Appointment{
					Day: day, Start: start, End: appointmentEnd,
					Doctor: doctor.Name, Trace: trace,
				}
				return Outcome{Appointment: found}
			}
		}
	}
	return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
}
