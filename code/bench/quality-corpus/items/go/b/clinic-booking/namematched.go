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
	state := prepareState(request)
	if err := firstProblem(state); err != nil {
		return Outcome{Err: err}
	}
	return outcomeOf(earliestAppointment(state, eligibleDoctors(state), candidateDays(state)))
}
func prepareState(request Request) prepared {
	request.Doctors = trimDoctorNames(request.Doctors)
	request.Bookings = trimBookingDoctors(request.Bookings)
	return buildState(request)
}
func trimDoctorNames(doctors []Doctor) []Doctor {
	cleaned := make([]Doctor, len(doctors))
	for index, doctor := range doctors {
		cleaned[index] = trimDoctorName(doctor)
	}
	return cleaned
}
func trimDoctorName(doctor Doctor) Doctor {
	return Doctor{Name: trimSpaces(doctor.Name), Windows: doctor.Windows}
}
func trimBookingDoctors(bookings []Booking) []Booking {
	cleaned := make([]Booking, len(bookings))
	for index, booking := range bookings {
		cleaned[index] = trimBookingDoctor(booking)
	}
	return cleaned
}
func trimBookingDoctor(booking Booking) Booking {
	cleaned := Booking{Day: booking.Day, Start: booking.Start, End: booking.End}
	cleaned.Doctor = trimSpaces(booking.Doctor)
	return cleaned
}
func buildState(request Request) prepared {
	preferred := trimSpaces(request.PreferredDoctor)
	preferredKey, _ := keyFromName(preferred)
	keys := doctorKeys(request.Doctors)
	return prepared{
		request: request, kind: normalizedKind(request.Kind), preferred: preferred,
		preferredKey: preferredKey, keys: keys, names: nameSet(keys),
		bookingKeys: bookingKeyList(request.Bookings),
	}
}
func doctorKeys(doctors []Doctor) []string {
	keys := make([]string, len(doctors))
	for index, doctor := range doctors {
		keys[index] = doctorKey(doctor.Name)
	}
	return keys
}
func bookingKeyList(bookings []Booking) []string {
	keys := make([]string, len(bookings))
	for index, booking := range bookings {
		keys[index] = doctorKey(booking.Doctor)
	}
	return keys
}
func doctorKey(name string) string {
	key, _ := keyFromName(name)
	return key
}
func keyFromName(name string) (string, bool) {
	if !nameRule.MatchString(name) {
		return "", false
	}
	return lowercase(name), true
}
func nameSet(keys []string) map[string]bool {
	names := make(map[string]bool, len(keys))
	for _, key := range keys {
		addNameKey(names, key)
	}
	return names
}
func addNameKey(names map[string]bool, key string) {
	if key != "" {
		names[key] = true
	}
}
func normalizedKind(value string) string { return lowercase(trimSpaces(value)) }
func trimSpaces(value string) string     { return strings.Trim(value, " ") }
func lowercase(value string) string      { return strings.ToLower(value) }

func firstProblem(state prepared) *ClinicError {
	if err := checkRequestFields(state); err != nil {
		return err
	}
	return checkBookingFields(state)
}
func checkRequestFields(state prepared) *ClinicError {
	if err := checkBounds(state); err != nil {
		return err
	}
	if err := checkDoctorList(state); err != nil {
		return err
	}
	return checkDoctorWindows(state)
}
func checkBookingFields(state prepared) *ClinicError {
	if err := checkHolidayList(state); err != nil {
		return err
	}
	if err := checkBookingList(state); err != nil {
		return err
	}
	return checkRequestOrder(state)
}
func checkBounds(state prepared) *ClinicError {
	if !scalarsInRange(state.request) || !isKnownKind(state.kind) {
		return errorWithCode("BAD_REQUEST")
	}
	return nil
}
func scalarsInRange(request Request) bool {
	return inRange(request.NowDay, maxDay) &&
		inRange(request.RequestedDay, maxDay) &&
		inRange(request.NowMinute, 1439) &&
		inRange(request.HorizonDays, horizonLimit)
}
func inRange(value, limit int) bool { return value >= 0 && value <= limit }
func isKnownKind(kind string) bool {
	_, known := kindRules[kind]
	return known
}
func checkDoctorList(state prepared) *ClinicError {
	if len(state.keys) < 1 || len(state.keys) > 12 {
		return errorWithCode("BAD_DOCTORS")
	}
	return firstBadDoctorKey(state.keys)
}
func firstBadDoctorKey(keys []string) *ClinicError {
	seen := make(map[string]bool, len(keys))
	for index, key := range keys {
		if key == "" || seen[key] {
			return errorAtIndex("BAD_DOCTORS", index)
		}
		seen[key] = true
	}
	return nil
}
func checkDoctorWindows(state prepared) *ClinicError {
	for index, doctor := range state.request.Doctors {
		if len(doctor.Windows) > 8 || !allWindowsValid(doctor.Windows) {
			return errorAtIndex("BAD_WINDOW", index)
		}
	}
	return nil
}
func allWindowsValid(windows []Window) bool {
	for _, window := range windows {
		if !windowInRange(window) {
			return false
		}
	}
	return true
}
func windowInRange(window Window) bool {
	inside := window.Weekday >= 0 && window.Weekday <= 6
	hours := window.Open >= 0 && window.Open < window.Close && window.Close <= 1440
	return inside && hours
}
func checkHolidayList(state prepared) *ClinicError {
	holidays := state.request.Holidays
	if len(holidays) > 60 {
		return errorWithCode("BAD_HOLIDAY")
	}
	return firstBadHoliday(holidays)
}
func firstBadHoliday(holidays []int) *ClinicError {
	seen := make(map[int]bool, len(holidays))
	for index, day := range holidays {
		if !holidayInRange(day) || seen[day] {
			return errorAtIndex("BAD_HOLIDAY", index)
		}
		seen[day] = true
	}
	return nil
}
func holidayInRange(day int) bool { return inRange(day, maxDay) }
func checkBookingList(state prepared) *ClinicError {
	if len(state.request.Bookings) > 200 {
		return errorWithCode("BAD_BOOKING")
	}
	return firstBadBooking(state)
}
func firstBadBooking(state prepared) *ClinicError {
	for index, booking := range state.request.Bookings {
		if !bookingInRange(booking) || !bookingDoctorKnown(state, index) {
			return errorAtIndex("BAD_BOOKING", index)
		}
	}
	return nil
}
func bookingInRange(booking Booking) bool {
	placed := booking.Day >= 0 && booking.Day <= maxDay && booking.Start >= 0
	ordered := booking.Start < booking.End && booking.End <= 1440
	return placed && ordered
}
func bookingDoctorKnown(state prepared, index int) bool {
	key := state.bookingKeys[index]
	return key != "" && state.names[key]
}
func checkRequestOrder(state prepared) *ClinicError {
	if state.preferred != "" && !state.names[state.preferredKey] {
		return errorWithCode("UNKNOWN_DOCTOR")
	}
	if !dayGapAllowed(state.request) {
		return errorWithCode("BAD_DAY_ORDER")
	}
	return nil
}
func dayGapAllowed(request Request) bool {
	gap := request.RequestedDay - request.NowDay
	return gap >= 0 && gap <= 8
}
func errorWithCode(code string) *ClinicError { return &ClinicError{Code: code} }
func errorAtIndex(code string, index int) *ClinicError {
	return &ClinicError{Code: code, Index: &index}
}

func eligibleDoctors(state prepared) []doctorEntry {
	entries := allDoctorEntries(state)
	if narrowedToPreferred(state) {
		return sortedByKey(entriesForDoctor(entries, state.preferredKey))
	}
	return sortedByKey(entries)
}
func narrowedToPreferred(state prepared) bool {
	return !state.request.Urgent && state.preferred != ""
}
func allDoctorEntries(state prepared) []doctorEntry {
	entries := make([]doctorEntry, 0, len(state.request.Doctors))
	for index, doctor := range state.request.Doctors {
		entries = append(entries, doctorEntry{key: state.keys[index], doctor: doctor})
	}
	return entries
}
func entriesForDoctor(entries []doctorEntry, key string) []doctorEntry {
	kept := make([]doctorEntry, 0, len(entries))
	for _, entry := range entries {
		if entry.key == key {
			kept = append(kept, entry)
		}
	}
	return kept
}
func sortedByKey(entries []doctorEntry) []doctorEntry {
	sort.Slice(entries, func(i, j int) bool { return entries[i].key < entries[j].key })
	return entries
}
func candidateDays(state prepared) []int {
	first := state.request.RequestedDay
	last := first + state.request.HorizonDays
	if last > maxDay {
		last = maxDay
	}
	return openDaysBetween(first, last, holidaySet(state.request.Holidays))
}
func holidaySet(holidays []int) map[int]bool {
	closed := make(map[int]bool, len(holidays))
	for _, day := range holidays {
		closed[day] = true
	}
	return closed
}
func openDaysBetween(first, last int, closed map[int]bool) []int {
	out := make([]int, 0, last-first+1)
	for day := first; day <= last; day++ {
		if !closed[day] {
			out = append(out, day)
		}
	}
	return out
}
func earliestAppointment(state prepared, entries []doctorEntry, dayList []int) *Appointment {
	rule := kindRules[state.kind]
	for _, day := range dayList {
		if found, ok := firstSlotOfDay(state, entries, rule, day); ok {
			return found
		}
	}
	return nil
}
func firstSlotOfDay(state prepared, entries []doctorEntry, rule kindRule,
	day int) (*Appointment, bool) {
	for start := 0; start <= 1435; start += 5 {
		if found, ok := firstSlotAtStart(state, entries, rule, day, start); ok {
			return appointmentOf(found), true
		}
	}
	return nil, false
}
func firstSlotAtStart(state prepared, entries []doctorEntry, rule kindRule,
	day, start int) (slot, bool) {
	end := start + rule.duration
	for _, entry := range entries {
		if slotIsFree(state, entry, day, start, end+rule.buffer) {
			return slot{day, start, end, entry.doctor.Name}, true
		}
	}
	return slot{}, false
}
func slotIsFree(state prepared, entry doctorEntry, day, start, reserved int) bool {
	open := fitsOpeningAndWindow(entry.doctor, day%7, start, reserved)
	return open && scheduleIsOpen(state, day, start, reserved, entry.key)
}
func fitsOpeningAndWindow(doctor Doctor, weekday, start, reserved int) bool {
	if !withinOpeningHours(weekday, start, reserved) || crossesLunch(start, reserved) {
		return false
	}
	return withinDoctorWindow(doctor, weekday, start, reserved)
}
func withinOpeningHours(weekday, start, reserved int) bool {
	hours := openingHours[weekday]
	return start >= hours[0] && reserved <= hours[1]
}
func crossesLunch(start, reserved int) bool {
	return start < lunchEnd && reserved > lunchStart
}
func withinDoctorWindow(doctor Doctor, weekday, start, reserved int) bool {
	for _, window := range doctor.Windows {
		if window.Weekday != weekday || window.Open > start || reserved > window.Close {
			continue
		}
		return true
	}
	return false
}
func scheduleIsOpen(state prepared, day, start, reserved int, key string) bool {
	if insideNoticeWindow(state.request, day, start) {
		return false
	}
	booked := bookingsFor(state, day, key)
	return len(booked) < dailyCap && noBookingOverlap(booked, start, reserved)
}
func insideNoticeWindow(request Request, day, start int) bool {
	return day == request.NowDay && start < request.NowMinute+noticeMinutes
}
func bookingsFor(state prepared, day int, key string) []Booking {
	booked := make([]Booking, 0, len(state.request.Bookings))
	for index, booking := range state.request.Bookings {
		if booking.Day == day && state.bookingKeys[index] == key {
			booked = append(booked, booking)
		}
	}
	return booked
}
func noBookingOverlap(booked []Booking, start, reserved int) bool {
	for _, booking := range booked {
		if start < booking.End && booking.Start < reserved {
			return false
		}
	}
	return true
}
func appointmentOf(found slot) *Appointment {
	return &Appointment{
		Day: found.day, Start: found.start, End: found.end,
		Doctor: found.doctor, Trace: traceLabels(),
	}
}
func traceLabels() []string {
	return []string{
		"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
		"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
		"earliest-grid-slot",
	}
}
func outcomeOf(found *Appointment) Outcome {
	if found == nil {
		return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
	}
	return Outcome{Appointment: found}
}
