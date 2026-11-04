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
	state := prep(request)
	if err := verify(state); err != nil {
		return Outcome{Err: err}
	}
	return result(earliest(state, eligible(state), days(state)))
}
func prep(request Request) prepared {
	request.Doctors = cleanDoctors(request.Doctors)
	request.Bookings = cleanBookings(request.Bookings)
	return makeState(request)
}
func cleanDoctors(doctors []Doctor) []Doctor {
	cleaned := make([]Doctor, len(doctors))
	for index, doctor := range doctors {
		cleaned[index] = cleanDoctor(doctor)
	}
	return cleaned
}
func cleanDoctor(doctor Doctor) Doctor {
	return Doctor{Name: trimText(doctor.Name), Windows: doctor.Windows}
}
func cleanBookings(bookings []Booking) []Booking {
	cleaned := make([]Booking, len(bookings))
	for index, booking := range bookings {
		cleaned[index] = cleanBooking(booking)
	}
	return cleaned
}
func cleanBooking(booking Booking) Booking {
	cleaned := Booking{Day: booking.Day, Start: booking.Start, End: booking.End}
	cleaned.Doctor = trimText(booking.Doctor)
	return cleaned
}
func makeState(request Request) prepared {
	preferred := trimText(request.PreferredDoctor)
	preferredKey, _ := nameKey(preferred)
	keys := keysOf(request.Doctors)
	return prepared{
		request: request, kind: kindOf(request.Kind), preferred: preferred,
		preferredKey: preferredKey, keys: keys, names: keySet(keys),
		bookingKeys: bookingKeysOf(request.Bookings),
	}
}
func keysOf(doctors []Doctor) []string {
	keys := make([]string, len(doctors))
	for index, doctor := range doctors {
		keys[index] = keyOrEmpty(doctor.Name)
	}
	return keys
}
func bookingKeysOf(bookings []Booking) []string {
	keys := make([]string, len(bookings))
	for index, booking := range bookings {
		keys[index] = keyOrEmpty(booking.Doctor)
	}
	return keys
}
func keyOrEmpty(name string) string {
	key, _ := nameKey(name)
	return key
}
func nameKey(name string) (string, bool) {
	if !nameRule.MatchString(name) {
		return "", false
	}
	return lowerText(name), true
}
func keySet(keys []string) map[string]bool {
	names := make(map[string]bool, len(keys))
	for _, key := range keys {
		addKey(names, key)
	}
	return names
}
func addKey(names map[string]bool, key string) {
	if key != "" {
		names[key] = true
	}
}
func kindOf(value string) string    { return lowerText(trimText(value)) }
func trimText(value string) string  { return strings.Trim(value, " ") }
func lowerText(value string) string { return strings.ToLower(value) }

func verify(state prepared) *ClinicError {
	if err := requestChecks(state); err != nil {
		return err
	}
	return bookingChecks(state)
}
func requestChecks(state prepared) *ClinicError {
	if err := checkScalars(state); err != nil {
		return err
	}
	if err := checkDoctors(state); err != nil {
		return err
	}
	return checkWindows(state)
}
func bookingChecks(state prepared) *ClinicError {
	if err := checkHolidays(state); err != nil {
		return err
	}
	if err := checkBookings(state); err != nil {
		return err
	}
	return checkOrder(state)
}
func checkScalars(state prepared) *ClinicError {
	if !bounds(state.request) || !knownKind(state.kind) {
		return fail("BAD_REQUEST")
	}
	return nil
}
func bounds(request Request) bool {
	return within(request.NowDay, maxDay) &&
		within(request.RequestedDay, maxDay) &&
		within(request.NowMinute, 1439) &&
		within(request.HorizonDays, horizonLimit)
}
func within(value, limit int) bool { return value >= 0 && value <= limit }
func knownKind(kind string) bool {
	_, known := kindRules[kind]
	return known
}
func checkDoctors(state prepared) *ClinicError {
	if len(state.keys) < 1 || len(state.keys) > 12 {
		return fail("BAD_DOCTORS")
	}
	return dupKeys(state.keys)
}
func dupKeys(keys []string) *ClinicError {
	seen := make(map[string]bool, len(keys))
	for index, key := range keys {
		if key == "" || seen[key] {
			return failAt("BAD_DOCTORS", index)
		}
		seen[key] = true
	}
	return nil
}
func checkWindows(state prepared) *ClinicError {
	for index, doctor := range state.request.Doctors {
		if len(doctor.Windows) > 8 || !allWindows(doctor.Windows) {
			return failAt("BAD_WINDOW", index)
		}
	}
	return nil
}
func allWindows(windows []Window) bool {
	for _, window := range windows {
		if !validWindow(window) {
			return false
		}
	}
	return true
}
func validWindow(window Window) bool {
	inside := window.Weekday >= 0 && window.Weekday <= 6
	hours := window.Open >= 0 && window.Open < window.Close && window.Close <= 1440
	return inside && hours
}
func checkHolidays(state prepared) *ClinicError {
	holidays := state.request.Holidays
	if len(holidays) > 60 {
		return fail("BAD_HOLIDAY")
	}
	return dupDays(holidays)
}
func dupDays(holidays []int) *ClinicError {
	seen := make(map[int]bool, len(holidays))
	for index, day := range holidays {
		if !dayInRange(day) || seen[day] {
			return failAt("BAD_HOLIDAY", index)
		}
		seen[day] = true
	}
	return nil
}
func dayInRange(day int) bool { return within(day, maxDay) }
func checkBookings(state prepared) *ClinicError {
	if len(state.request.Bookings) > 200 {
		return fail("BAD_BOOKING")
	}
	return unfitBooking(state)
}
func unfitBooking(state prepared) *ClinicError {
	for index, booking := range state.request.Bookings {
		if !spanOK(booking) || !keyKnown(state, index) {
			return failAt("BAD_BOOKING", index)
		}
	}
	return nil
}
func spanOK(booking Booking) bool {
	placed := booking.Day >= 0 && booking.Day <= maxDay && booking.Start >= 0
	ordered := booking.Start < booking.End && booking.End <= 1440
	return placed && ordered
}
func keyKnown(state prepared, index int) bool {
	key := state.bookingKeys[index]
	return key != "" && state.names[key]
}
func checkOrder(state prepared) *ClinicError {
	if state.preferred != "" && !state.names[state.preferredKey] {
		return fail("UNKNOWN_DOCTOR")
	}
	if !dayOrder(state.request) {
		return fail("BAD_DAY_ORDER")
	}
	return nil
}
func dayOrder(request Request) bool {
	gap := request.RequestedDay - request.NowDay
	return gap >= 0 && gap <= 8
}
func fail(code string) *ClinicError { return &ClinicError{Code: code} }
func failAt(code string, index int) *ClinicError {
	return &ClinicError{Code: code, Index: &index}
}

func eligible(state prepared) []doctorEntry {
	entries := pairs(state)
	if restricted(state) {
		return byKey(onlyKey(entries, state.preferredKey))
	}
	return byKey(entries)
}
func restricted(state prepared) bool {
	return !state.request.Urgent && state.preferred != ""
}
func pairs(state prepared) []doctorEntry {
	entries := make([]doctorEntry, 0, len(state.request.Doctors))
	for index, doctor := range state.request.Doctors {
		entries = append(entries, doctorEntry{key: state.keys[index], doctor: doctor})
	}
	return entries
}
func onlyKey(entries []doctorEntry, key string) []doctorEntry {
	kept := make([]doctorEntry, 0, len(entries))
	for _, entry := range entries {
		if entry.key == key {
			kept = append(kept, entry)
		}
	}
	return kept
}
func byKey(entries []doctorEntry) []doctorEntry {
	sort.Slice(entries, func(i, j int) bool { return entries[i].key < entries[j].key })
	return entries
}
func days(state prepared) []int {
	first := state.request.RequestedDay
	last := first + state.request.HorizonDays
	if last > maxDay {
		last = maxDay
	}
	return openDays(first, last, closedSet(state.request.Holidays))
}
func closedSet(holidays []int) map[int]bool {
	closed := make(map[int]bool, len(holidays))
	for _, day := range holidays {
		closed[day] = true
	}
	return closed
}
func openDays(first, last int, closed map[int]bool) []int {
	out := make([]int, 0, last-first+1)
	for day := first; day <= last; day++ {
		if !closed[day] {
			out = append(out, day)
		}
	}
	return out
}
func earliest(state prepared, entries []doctorEntry, dayList []int) *Appointment {
	rule := kindRules[state.kind]
	for _, day := range dayList {
		if found, ok := findDay(state, entries, rule, day); ok {
			return found
		}
	}
	return nil
}
func findDay(state prepared, entries []doctorEntry, rule kindRule, day int) (*Appointment, bool) {
	for start := 0; start <= 1435; start += 5 {
		if found, ok := atStart(state, entries, rule, day, start); ok {
			return pack(found), true
		}
	}
	return nil, false
}
func atStart(state prepared, entries []doctorEntry, rule kindRule, day, start int) (slot, bool) {
	end := start + rule.duration
	for _, entry := range entries {
		if slotFree(state, entry, day, start, end+rule.buffer) {
			return slot{day, start, end, entry.doctor.Name}, true
		}
	}
	return slot{}, false
}
func slotFree(state prepared, entry doctorEntry, day, start, reserved int) bool {
	open := fits(entry.doctor, day%7, start, reserved)
	return open && free(state, day, start, reserved, entry.key)
}
func fits(doctor Doctor, weekday, start, reserved int) bool {
	if !openOK(weekday, start, reserved) || lunchHit(start, reserved) {
		return false
	}
	return windowOK(doctor, weekday, start, reserved)
}
func openOK(weekday, start, reserved int) bool {
	hours := openingHours[weekday]
	return start >= hours[0] && reserved <= hours[1]
}
func lunchHit(start, reserved int) bool {
	return start < lunchEnd && reserved > lunchStart
}
func windowOK(doctor Doctor, weekday, start, reserved int) bool {
	for _, window := range doctor.Windows {
		if window.Weekday != weekday || window.Open > start || reserved > window.Close {
			continue
		}
		return true
	}
	return false
}
func free(state prepared, day, start, reserved int, key string) bool {
	if tooSoon(state.request, day, start) {
		return false
	}
	booked := rowsAt(state, day, key)
	return len(booked) < dailyCap && noClash(booked, start, reserved)
}
func tooSoon(request Request, day, start int) bool {
	return day == request.NowDay && start < request.NowMinute+noticeMinutes
}
func rowsAt(state prepared, day int, key string) []Booking {
	booked := make([]Booking, 0, len(state.request.Bookings))
	for index, booking := range state.request.Bookings {
		if booking.Day == day && state.bookingKeys[index] == key {
			booked = append(booked, booking)
		}
	}
	return booked
}
func noClash(booked []Booking, start, reserved int) bool {
	for _, booking := range booked {
		if start < booking.End && booking.Start < reserved {
			return false
		}
	}
	return true
}
func pack(found slot) *Appointment {
	return &Appointment{
		Day: found.day, Start: found.start, End: found.end,
		Doctor: found.doctor, Trace: trace(),
	}
}
func trace() []string {
	return []string{
		"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
		"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
		"earliest-grid-slot",
	}
}
func result(found *Appointment) Outcome {
	if found == nil {
		return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
	}
	return Outcome{Appointment: found}
}
