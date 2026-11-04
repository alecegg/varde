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
type traceLog struct {
	seen   map[string]bool
	labels []string
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
	log := &traceLog{seen: make(map[string]bool, 10)}
	doctors, keys := trimDoctors(request.Doctors)
	bookings, bookingKeys := trimBookings(request.Bookings)
	preferred := strings.Trim(request.PreferredDoctor, " ")
	preferredKey, _ := doctorNameKey(preferred)
	names := make(map[string]bool, len(keys))
	for _, key := range keys {
		if key != "" {
			names[key] = true
		}
	}
	request.Doctors, request.Bookings = doctors, bookings
	kind := strings.ToLower(strings.Trim(request.Kind, " "))
	state := prepared{
		request:      request,
		kind:         kind,
		preferred:    preferred,
		preferredKey: preferredKey,
		keys:         keys,
		names:        names,
		bookingKeys:  bookingKeys,
	}
	noteLabel(log, "normalised")
	if problem := validateRequest(state); problem != nil {
		return Outcome{Err: problem}
	}
	noteLabel(log, "validated")
	found, ok := findEarliest(state, log)
	if !ok {
		return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
	}
	appointment := &Appointment{
		Day:    found.day,
		Start:  found.start,
		End:    found.end,
		Doctor: found.doctor,
		Trace:  log.labels,
	}
	return Outcome{Appointment: appointment}
}
func noteLabel(log *traceLog, label string) {
	if log.seen[label] {
		return
	}
	log.seen[label] = true
	log.labels = append(log.labels, label)
}
func trimDoctors(doctors []Doctor) ([]Doctor, []string) {
	trimmed := make([]Doctor, len(doctors))
	keys := make([]string, len(doctors))
	for index, doctor := range doctors {
		name := strings.Trim(doctor.Name, " ")
		key, _ := doctorNameKey(name)
		trimmed[index] = Doctor{Name: name, Windows: doctor.Windows}
		keys[index] = key
	}
	return trimmed, keys
}
func trimBookings(bookings []Booking) ([]Booking, []string) {
	trimmed := make([]Booking, len(bookings))
	keys := make([]string, len(bookings))
	for index, booking := range bookings {
		name := strings.Trim(booking.Doctor, " ")
		key, _ := doctorNameKey(name)
		cleaned := Booking{Day: booking.Day, Start: booking.Start, End: booking.End}
		cleaned.Doctor = name
		trimmed[index] = cleaned
		keys[index] = key
	}
	return trimmed, keys
}
func doctorNameKey(name string) (string, bool) {
	if !nameRule.MatchString(name) {
		return "", false
	}
	key := strings.ToLower(name)
	return key, true
}
func validateRequest(state prepared) *ClinicError {
	if problem := checkScalarRanges(state.request, state.kind); problem != nil {
		return problem
	}
	if problem := checkDoctorList(state); problem != nil {
		return problem
	}
	if problem := checkDoctorWindows(state); problem != nil {
		return problem
	}
	if problem := checkHolidayList(state); problem != nil {
		return problem
	}
	if problem := checkBookingList(state); problem != nil {
		return problem
	}
	if problem := checkPreferenceAndOrder(state); problem != nil {
		return problem
	}
	return nil
}
func checkScalarRanges(request Request, kind string) *ClinicError {
	dayIsValid := request.NowDay >= 0 && request.NowDay <= maxDay
	requestedIsValid := request.RequestedDay >= 0 && request.RequestedDay <= maxDay
	minuteIsValid := request.NowMinute >= 0 && request.NowMinute <= 1439
	horizonIsValid := request.HorizonDays >= 0 && request.HorizonDays <= horizonLimit
	_, kindIsKnown := kindRules[kind]
	scalarsAreValid := dayIsValid && requestedIsValid && minuteIsValid
	scalarsAreValid = scalarsAreValid && horizonIsValid && kindIsKnown
	if !scalarsAreValid {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	return nil
}
func checkDoctorList(state prepared) *ClinicError {
	count := len(state.keys)
	countIsOutOfRange := count < 1 || count > 12
	if countIsOutOfRange {
		return &ClinicError{Code: "BAD_DOCTORS"}
	}
	seen := make(map[string]bool, count)
	for index, key := range state.keys {
		position := index
		nameIsUnusable := key == "" || seen[key]
		if nameIsUnusable {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &position}
		}
		seen[key] = true
	}
	return nil
}
func checkDoctorWindows(state prepared) *ClinicError {
	for index, doctor := range state.request.Doctors {
		position := index
		if len(doctor.Windows) > 8 {
			return &ClinicError{Code: "BAD_WINDOW", Index: &position}
		}
		for _, window := range doctor.Windows {
			weekdayIsOutOfRange := window.Weekday < 0 || window.Weekday > 6
			spanIsOutOfRange := window.Open < 0 || window.Open >= window.Close
			if weekdayIsOutOfRange || spanIsOutOfRange || window.Close > 1440 {
				return &ClinicError{Code: "BAD_WINDOW", Index: &position}
			}
		}
	}
	return nil
}
func checkHolidayList(state prepared) *ClinicError {
	holidays := state.request.Holidays
	if len(holidays) > 60 {
		return &ClinicError{Code: "BAD_HOLIDAY"}
	}
	seen := make(map[int]bool, len(holidays))
	for index, day := range holidays {
		position := index
		dayIsOutOfRange := day < 0 || day > maxDay
		if dayIsOutOfRange || seen[day] {
			return &ClinicError{Code: "BAD_HOLIDAY", Index: &position}
		}
		seen[day] = true
	}
	return nil
}
func checkBookingList(state prepared) *ClinicError {
	bookings := state.request.Bookings
	if len(bookings) > 200 {
		return &ClinicError{Code: "BAD_BOOKING"}
	}
	for index, booking := range bookings {
		if problem := checkBookingLine(state, index, booking); problem != nil {
			return problem
		}
	}
	return nil
}
func checkBookingLine(state prepared, index int, booking Booking) *ClinicError {
	key := state.bookingKeys[index]
	dayIsInvalid := booking.Day < 0 || booking.Day > maxDay
	spanIsInvalid := booking.Start < 0 || booking.Start >= booking.End
	doctorIsInvalid := key == "" || !state.names[key]
	bookingIsInvalid := dayIsInvalid || spanIsInvalid || doctorIsInvalid
	if bookingIsInvalid || booking.End > 1440 {
		return &ClinicError{Code: "BAD_BOOKING", Index: &index}
	}
	return nil
}
func checkPreferenceAndOrder(state prepared) *ClinicError {
	if state.preferred != "" && !state.names[state.preferredKey] {
		return &ClinicError{Code: "UNKNOWN_DOCTOR"}
	}
	request := state.request
	gap := request.RequestedDay - request.NowDay
	if gap < 0 || gap > 8 {
		return &ClinicError{Code: "BAD_DAY_ORDER"}
	}
	return nil
}
func findEarliest(state prepared, log *traceLog) (slot, bool) {
	entries := sortedEntries(state)
	rule := kindRules[state.kind]
	for _, day := range candidateDays(state, log) {
		for start := 0; start <= 1435; start += 5 {
			found, ok := firstFittingSlot(state, entries, rule, day, start, log)
			if ok {
				noteLabel(log, "earliest-grid-slot")
				return found, true
			}
		}
	}
	return slot{}, false
}
func sortedEntries(state prepared) []doctorEntry {
	entries := make([]doctorEntry, len(state.request.Doctors))
	for index, doctor := range state.request.Doctors {
		entries[index] = doctorEntry{key: state.keys[index], doctor: doctor}
	}
	sort.Slice(entries, func(left, right int) bool {
		return entries[left].key < entries[right].key
	})
	return entries
}
func candidateDays(state prepared, log *traceLog) []int {
	first := state.request.RequestedDay
	last := first + state.request.HorizonDays
	closed := make(map[int]bool, len(state.request.Holidays))
	for _, day := range state.request.Holidays {
		closed[day] = true
	}
	var days []int
	for day := first; day <= last && day <= maxDay; day++ {
		if closed[day] {
			continue
		}
		days = append(days, day)
	}
	noteLabel(log, "holiday-filter")
	return days
}
func firstFittingSlot(
	state prepared,
	entries []doctorEntry,
	rule kindRule,
	day, start int,
	log *traceLog,
) (slot, bool) {
	reservedEnd := start + rule.duration + rule.buffer
	for _, entry := range entries {
		if acceptsTimeRules(state, entry, day, start, reservedEnd, log) &&
			acceptsBookingRules(state, entry, day, start, reservedEnd, log) {
			found := slot{
				day: day, start: start, end: start + rule.duration,
				doctor: entry.doctor.Name,
			}
			return found, true
		}
	}
	return slot{}, false
}
func acceptsTimeRules(
	state prepared,
	entry doctorEntry,
	day, start, reservedEnd int,
	log *traceLog,
) bool {
	weekday := day % 7
	if !fitsOpeningHours(weekday, start, reservedEnd) {
		return false
	}
	noteLabel(log, "hours-and-lunch")
	noticeThreshold := state.request.NowMinute + noticeMinutes
	if day == state.request.NowDay && start < noticeThreshold {
		return false
	}
	noteLabel(log, "notice")
	if !withinDoctorWindow(entry.doctor, weekday, start, reservedEnd) {
		return false
	}
	noteLabel(log, "doctor-availability")
	return true
}
func acceptsBookingRules(
	state prepared,
	entry doctorEntry,
	day, start, reservedEnd int,
	log *traceLog,
) bool {
	if !bookingLoadAllows(state, entry.key, day, start, reservedEnd) {
		return false
	}
	noteLabel(log, "daily-cap")
	noteLabel(log, "booking-conflicts")
	restricted := !state.request.Urgent && state.preferred != ""
	if restricted && entry.key != state.preferredKey {
		return false
	}
	noteLabel(log, "urgent-priority")
	return true
}
func fitsOpeningHours(weekday, start, reservedEnd int) bool {
	hours := openingHours[weekday]
	opensAt := hours[0]
	shutsAt := hours[1]
	if start < opensAt || reservedEnd > shutsAt {
		return false
	}
	intersectsLunch := start < lunchEnd && reservedEnd > lunchStart
	if intersectsLunch {
		return false
	}
	return true
}
func withinDoctorWindow(doctor Doctor, weekday, start, reservedEnd int) bool {
	for _, window := range doctor.Windows {
		if window.Weekday != weekday {
			continue
		}
		startsTooEarly := window.Open > start
		if startsTooEarly {
			continue
		}
		endsTooLate := reservedEnd > window.Close
		if endsTooLate {
			continue
		}
		return true
	}
	return false
}
func bookingLoadAllows(state prepared, key string, day, start, reservedEnd int) bool {
	count := 0
	for index, booking := range state.request.Bookings {
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
