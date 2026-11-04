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
type doctorEntry struct {
	key    string
	doctor Doctor
}
type slot struct {
	day, start, end int
	doctor          string
}
type prepared struct {
	request      Request
	kind         string
	preferred    string
	preferredKey string
	keys         []string
	names        map[string]bool
	bookingKeys  []string
}

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
	state := prepare(request)
	if err := validate(state); err != nil {
		return Outcome{Err: err}
	}
	found := earliest(state)
	if found == nil {
		return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
	}
	return Outcome{Appointment: found}
}
func prepare(request Request) prepared {
	doctors, keys := normaliseDoctors(request.Doctors)
	bookings, bookingKeys := normaliseBookings(request.Bookings)
	preferred := strings.Trim(request.PreferredDoctor, " ")
	preferredKey, _ := nameKey(preferred)
	names := make(map[string]bool, len(keys))
	for _, key := range keys {
		if key != "" {
			names[key] = true
		}
	}
	request.Doctors, request.Bookings = doctors, bookings
	return prepared{
		request:      request,
		kind:         strings.ToLower(strings.Trim(request.Kind, " ")),
		preferred:    preferred,
		preferredKey: preferredKey,
		keys:         keys,
		names:        names,
		bookingKeys:  bookingKeys,
	}
}
func normaliseDoctors(doctors []Doctor) ([]Doctor, []string) {
	trimmed := make([]Doctor, len(doctors))
	keys := make([]string, len(doctors))
	for index, doctor := range doctors {
		name := strings.Trim(doctor.Name, " ")
		key, _ := nameKey(name)
		trimmed[index] = Doctor{Name: name, Windows: doctor.Windows}
		keys[index] = key
	}
	return trimmed, keys
}
func normaliseBookings(bookings []Booking) ([]Booking, []string) {
	trimmed := make([]Booking, len(bookings))
	keys := make([]string, len(bookings))
	for index, booking := range bookings {
		name := strings.Trim(booking.Doctor, " ")
		key, _ := nameKey(name)
		trimmed[index] = Booking{
			Day: booking.Day, Start: booking.Start, End: booking.End, Doctor: name,
		}
		keys[index] = key
	}
	return trimmed, keys
}
func nameKey(name string) (string, bool) {
	if !nameRule.MatchString(name) {
		return "", false
	}
	return strings.ToLower(name), true
}
func validate(state prepared) *ClinicError {
	checks := []func(prepared) *ClinicError{
		checkScalars, checkDoctors, checkWindows, checkHolidays, checkBookings, checkOrder,
	}
	for _, check := range checks {
		if err := check(state); err != nil {
			return err
		}
	}
	return nil
}
func checkScalars(state prepared) *ClinicError {
	request := state.request
	if request.NowDay < 0 || request.NowDay > maxDay {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if request.RequestedDay < 0 || request.RequestedDay > maxDay {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if request.NowMinute < 0 || request.NowMinute > 1439 {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if request.HorizonDays < 0 || request.HorizonDays > horizonLimit {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if _, known := kindRules[state.kind]; !known {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	return nil
}
func checkDoctors(state prepared) *ClinicError {
	if len(state.keys) < 1 || len(state.keys) > 12 {
		return &ClinicError{Code: "BAD_DOCTORS"}
	}
	seen := make(map[string]bool, len(state.keys))
	for index, key := range state.keys {
		position := index
		if key == "" || seen[key] {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &position}
		}
		seen[key] = true
	}
	return nil
}
func checkWindows(state prepared) *ClinicError {
	for index, doctor := range state.request.Doctors {
		position := index
		if len(doctor.Windows) > 8 {
			return &ClinicError{Code: "BAD_WINDOW", Index: &position}
		}
		for _, window := range doctor.Windows {
			badWeekday := window.Weekday < 0 || window.Weekday > 6
			badSpan := window.Open < 0 || window.Open >= window.Close
			if badWeekday || badSpan || window.Close > 1440 {
				return &ClinicError{Code: "BAD_WINDOW", Index: &position}
			}
		}
	}
	return nil
}
func checkHolidays(state prepared) *ClinicError {
	if len(state.request.Holidays) > 60 {
		return &ClinicError{Code: "BAD_HOLIDAY"}
	}
	seen := make(map[int]bool, len(state.request.Holidays))
	for index, day := range state.request.Holidays {
		position := index
		if day < 0 || day > maxDay || seen[day] {
			return &ClinicError{Code: "BAD_HOLIDAY", Index: &position}
		}
		seen[day] = true
	}
	return nil
}
func checkBookings(state prepared) *ClinicError {
	bookings := state.request.Bookings
	if len(bookings) > 200 {
		return &ClinicError{Code: "BAD_BOOKING"}
	}
	for index, booking := range bookings {
		position := index
		key := state.bookingKeys[index]
		badPlace := booking.Day < 0 || booking.Day > maxDay || booking.Start < 0
		badSpan := booking.Start >= booking.End || booking.End > 1440
		badDoctor := key == "" || !state.names[key]
		if badPlace || badSpan || badDoctor {
			return &ClinicError{Code: "BAD_BOOKING", Index: &position}
		}
	}
	return nil
}
func checkOrder(state prepared) *ClinicError {
	if state.preferred != "" && !state.names[state.preferredKey] {
		return &ClinicError{Code: "UNKNOWN_DOCTOR"}
	}
	request := state.request
	if request.RequestedDay < request.NowDay || request.RequestedDay-request.NowDay > 8 {
		return &ClinicError{Code: "BAD_DAY_ORDER"}
	}
	return nil
}
func earliest(state prepared) *Appointment {
	entries := eligibleDoctors(state)
	rule := kindRules[state.kind]
	for _, day := range candidateDays(state) {
		for start := 0; start <= 1435; start += 5 {
			if found, ok := firstCandidate(state, entries, rule, day, start); ok {
				return assemble(found)
			}
		}
	}
	return nil
}
func candidateDays(state prepared) []int {
	first := state.request.RequestedDay
	last := first + state.request.HorizonDays
	if last > maxDay {
		last = maxDay
	}
	closed := make(map[int]bool, len(state.request.Holidays))
	for _, day := range state.request.Holidays {
		closed[day] = true
	}
	days := make([]int, 0, last-first+1)
	for day := first; day <= last; day++ {
		if !closed[day] {
			days = append(days, day)
		}
	}
	return days
}
func eligibleDoctors(state prepared) []doctorEntry {
	restricted := !state.request.Urgent && state.preferred != ""
	entries := make([]doctorEntry, 0, len(state.request.Doctors))
	for index, doctor := range state.request.Doctors {
		key := state.keys[index]
		if restricted && key != state.preferredKey {
			continue
		}
		entries = append(entries, doctorEntry{key: key, doctor: doctor})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].key < entries[j].key })
	return entries
}
func firstCandidate(
	state prepared,
	entries []doctorEntry,
	rule kindRule,
	day, start int,
) (slot, bool) {
	reservedEnd := start + rule.duration + rule.buffer
	for _, entry := range entries {
		if !withinHours(entry.doctor, day%7, start, reservedEnd) {
			continue
		}
		if scheduleClear(state, day, start, reservedEnd, entry.key) {
			found := slot{day, start, start + rule.duration, entry.doctor.Name}
			return found, true
		}
	}
	return slot{}, false
}
func withinHours(doctor Doctor, weekday, start, reservedEnd int) bool {
	hours := openingHours[weekday]
	if start < hours[0] || reservedEnd > hours[1] {
		return false
	}
	if start < lunchEnd && reservedEnd > lunchStart {
		return false
	}
	for _, window := range doctor.Windows {
		if window.Weekday != weekday || window.Open > start || reservedEnd > window.Close {
			continue
		}
		return true
	}
	return false
}
func scheduleClear(state prepared, day, start, reservedEnd int, key string) bool {
	request := state.request
	if day == request.NowDay && start < request.NowMinute+noticeMinutes {
		return false
	}
	count := 0
	for index, booking := range request.Bookings {
		if booking.Day != day || state.bookingKeys[index] != key {
			continue
		}
		if start < booking.End && booking.Start < reservedEnd {
			return false
		}
		count++
	}
	return count < dailyCap
}
func assemble(found slot) *Appointment {
	trace := []string{
		"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
		"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
		"earliest-grid-slot",
	}
	return &Appointment{
		Day: found.day, Start: found.start, End: found.end,
		Doctor: found.doctor, Trace: trace,
	}
}
