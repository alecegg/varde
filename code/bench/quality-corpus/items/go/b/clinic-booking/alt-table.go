package corpus

import (
	"regexp"
	"sort"
	"strings"
)

type Request struct {
	NowDay, NowMinute, RequestedDay, HorizonDays int
	Kind                                         string
	Urgent                                       bool
	PreferredDoctor                              string
	Holidays                                     []int
	Doctors                                      []Doctor
	Bookings                                     []Booking
}
type Doctor struct {
	Name    string
	Windows []Window
}
type Window struct{ Weekday, Open, Close int }
type Booking struct {
	Day, Start, End int
	Doctor          string
}
type Appointment struct {
	Day, Start, End int
	Doctor          string
	Trace           []string
}
type ClinicError struct {
	Code  string
	Index *int
}
type Outcome struct {
	Appointment *Appointment
	Err         *ClinicError
}
type kindRow struct{ duration, buffer int }
type numberRange struct{ value, low, high int }
type doctorRow struct {
	record Doctor
	key    string
}
type bookingRow struct {
	record Booking
	key    string
}
type candidate struct {
	day, start int
	doctor     doctorRow
}
type span struct{ from, to int }
type ruleSpan struct {
	rule int
	span
}
type dayLimits struct {
	allowed []ruleSpan
	blocked []span
}

const (
	maximumDay      = 1_000_000
	maximumHorizon  = 14
	maximumHolidays = 60
	maximumDaily    = 4
	minimumNotice   = 60
	lunchBegins     = 720
	lunchEnds       = 780
	lastStart       = 1435
	openEnded       = 2880
	allRules        = 1<<3 - 1
)

var tableName = regexp.MustCompile(`^[A-Za-z0-9 -]+$`)
var kinds = map[string]kindRow{
	"checkup":      {20, 5},
	"consultation": {30, 10},
	"procedure":    {60, 15},
}
var lunch = span{lunchBegins, lunchEnds}
var weekdayHours = [7]span{
	{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
	{540, 1020}, {600, 840}, {0, 0},
}
var tableTrace = []string{
	"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
	"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
	"earliest-grid-slot",
}

// Solution validates the rows, then tests each candidate against per-day span data.
func Solution(request Request) Outcome {
	search := normalizeTableInput(request)
	if issue := validateTableInput(search); issue != nil {
		return Outcome{Err: issue}
	}
	if issue := validateBookingRows(search); issue != nil {
		return Outcome{Err: issue}
	}
	if issue := validatePreference(search); issue != nil {
		return Outcome{Err: issue}
	}
	if found := runCandidates(search); found != nil {
		return tableAppointment(search, found)
	}
	return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
}

func tableAppointment(search tableSearch, found *candidate) Outcome {
	return Outcome{Appointment: &Appointment{
		Day: found.day, Start: found.start, End: found.start + search.kind.duration,
		Doctor: found.doctor.record.Name, Trace: append([]string(nil), tableTrace...),
	}}
}

type tableSearch struct {
	request  Request
	kind     kindRow
	doctors  []doctorRow
	bookings []bookingRow
	known    map[string]bool
	closed   map[int]bool
}

func normalizeTableInput(request Request) tableSearch {
	kind := strings.ToLower(strings.Trim(request.Kind, " "))
	request.PreferredDoctor = strings.Trim(request.PreferredDoctor, " ")
	plan := tableSearch{
		request: request, kind: kinds[kind], closed: map[int]bool{},
		doctors:  normalizeDoctorRows(request.Doctors),
		bookings: normalizeBookingRows(request.Bookings),
		known:    map[string]bool{},
	}
	for _, doctor := range plan.doctors {
		plan.known[doctor.key] = true
	}
	for _, day := range request.Holidays {
		plan.closed[day] = true
	}
	return plan
}

func normalizeDoctorRows(rows []Doctor) []doctorRow {
	result := make([]doctorRow, len(rows))
	for index, doctor := range rows {
		doctor.Name = strings.Trim(doctor.Name, " ")
		result[index] = doctorRow{record: doctor, key: strings.ToLower(doctor.Name)}
	}
	return result
}

func normalizeBookingRows(rows []Booking) []bookingRow {
	result := make([]bookingRow, len(rows))
	for index, booking := range rows {
		booking.Doctor = strings.Trim(booking.Doctor, " ")
		result[index] = bookingRow{record: booking, key: strings.ToLower(booking.Doctor)}
	}
	return result
}

func validateTableInput(plan tableSearch) *ClinicError {
	if issue := validateScalarRows(plan); issue != nil {
		return issue
	}
	if issue := validateDoctorRows(plan.doctors); issue != nil {
		return issue
	}
	if issue := validateWindowRows(plan.doctors); issue != nil {
		return issue
	}
	return validateHolidayRows(plan.request.Holidays)
}

func validateScalarRows(plan tableSearch) *ClinicError {
	ranges := []numberRange{
		{plan.request.NowDay, 0, maximumDay},
		{plan.request.RequestedDay, 0, maximumDay},
		{plan.request.NowMinute, 0, 1439},
		{plan.request.HorizonDays, 0, maximumHorizon},
	}
	if plan.kind.duration == 0 || !rangesPass(ranges) {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	return nil
}

func rangesPass(rows []numberRange) bool {
	for _, row := range rows {
		if row.value < row.low || row.value > row.high {
			return false
		}
	}
	return true
}

func validateDoctorRows(doctors []doctorRow) *ClinicError {
	if len(doctors) < 1 || len(doctors) > 12 {
		return &ClinicError{Code: "BAD_DOCTORS"}
	}
	seen := make(map[string]bool, len(doctors))
	for index, doctor := range doctors {
		if !tableName.MatchString(doctor.record.Name) || seen[doctor.key] {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &index}
		}
		seen[doctor.key] = true
	}
	return nil
}

func validateWindowRows(doctors []doctorRow) *ClinicError {
	for index, doctor := range doctors {
		if len(doctor.record.Windows) > 8 {
			return &ClinicError{Code: "BAD_WINDOW", Index: &index}
		}
		for _, window := range doctor.record.Windows {
			ranges := []numberRange{
				{window.Weekday, 0, 6}, {window.Open, 0, 1439},
				{window.Close, 1, 1440},
			}
			if !rangesPass(ranges) || window.Open >= window.Close {
				return &ClinicError{Code: "BAD_WINDOW", Index: &index}
			}
		}
	}
	return nil
}

func validateHolidayRows(days []int) *ClinicError {
	if len(days) > maximumHolidays {
		return &ClinicError{Code: "BAD_HOLIDAY"}
	}
	seen := map[int]bool{}
	for index, day := range days {
		if day < 0 || day > maximumDay || seen[day] {
			return &ClinicError{Code: "BAD_HOLIDAY", Index: &index}
		}
		seen[day] = true
	}
	return nil
}

func validateBookingRows(plan tableSearch) *ClinicError {
	if len(plan.bookings) > 200 {
		return &ClinicError{Code: "BAD_BOOKING"}
	}
	for index, row := range plan.bookings {
		value := row.record
		ranges := []numberRange{
			{value.Day, 0, maximumDay}, {value.Start, 0, 1439}, {value.End, 1, 1440},
		}
		if !rangesPass(ranges) || value.Start >= value.End ||
			!tableName.MatchString(value.Doctor) || !plan.known[row.key] {
			return &ClinicError{Code: "BAD_BOOKING", Index: &index}
		}
	}
	return nil
}

func validatePreference(plan tableSearch) *ClinicError {
	named := plan.request.PreferredDoctor
	if named != "" && !(tableName.MatchString(named) && plan.known[strings.ToLower(named)]) {
		return &ClinicError{Code: "UNKNOWN_DOCTOR"}
	}
	if plan.request.RequestedDay < plan.request.NowDay ||
		plan.request.RequestedDay-plan.request.NowDay > 8 {
		return &ClinicError{Code: "BAD_DAY_ORDER"}
	}
	return nil
}

func prioritizedDoctors(plan tableSearch) []doctorRow {
	chosen := make([]doctorRow, 0, len(plan.doctors))
	named := plan.request.PreferredDoctor
	for _, doctor := range plan.doctors {
		if plan.request.Urgent || named == "" || doctor.key == strings.ToLower(named) {
			chosen = append(chosen, doctor)
		}
	}
	sort.Slice(chosen, func(i, j int) bool { return chosen[i].key < chosen[j].key })
	return chosen
}

func runCandidates(plan tableSearch) *candidate {
	doctors := prioritizedDoctors(plan)
	last := plan.request.RequestedDay + plan.request.HorizonDays
	if last > maximumDay {
		last = maximumDay
	}
	for day := plan.request.RequestedDay; day <= last; day++ {
		if plan.closed[day] {
			continue
		}
		limits := make([]dayLimits, len(doctors))
		for index, doctor := range doctors {
			limits[index] = limitsFor(plan, day, doctor)
		}
		if start, index, ok := earliestFit(limits, plan.kind); ok {
			return &candidate{day: day, start: start, doctor: doctors[index]}
		}
	}
	return nil
}

func earliestFit(limits []dayLimits, kind kindRow) (int, int, bool) {
	for start := 0; start <= lastStart; start += 5 {
		for index, limit := range limits {
			if fits(limit, start, start+kind.duration+kind.buffer) {
				return start, index, true
			}
		}
	}
	return 0, 0, false
}

// limitsFor numbers each constraint: a slot must lie inside one span of every
// numbered rule, and outside every blocked span (lunch, notice, bookings).
func limitsFor(plan tableSearch, day int, doctor doctorRow) dayLimits {
	hours := weekdayHours[day%7]
	booked := bookedSpans(plan.bookings, day, doctor.key)
	limits := dayLimits{
		allowed: append(windowSpans(doctor.record.Windows, day%7), ruleSpan{0, hours}),
		blocked: append([]span{lunch}, booked...),
	}
	if day == plan.request.NowDay {
		notice := span{0, plan.request.NowMinute + minimumNotice}
		limits.blocked = append(limits.blocked, notice)
	}
	if len(booked) < maximumDaily {
		limits.allowed = append(limits.allowed, ruleSpan{2, span{0, openEnded}})
	}
	return limits
}

func windowSpans(windows []Window, weekday int) []ruleSpan {
	var spans []ruleSpan
	for _, window := range windows {
		if window.Weekday == weekday {
			spans = append(spans, ruleSpan{1, span{window.Open, window.Close}})
		}
	}
	return spans
}

func bookedSpans(bookings []bookingRow, day int, key string) []span {
	var spans []span
	for _, booking := range bookings {
		if booking.record.Day == day && booking.key == key {
			spans = append(spans, span{booking.record.Start, booking.record.End})
		}
	}
	return spans
}

func fits(limits dayLimits, start, reserved int) bool {
	met := 0
	for _, allowed := range limits.allowed {
		if allowed.from <= start && reserved <= allowed.to {
			met |= 1 << allowed.rule
		}
	}
	for _, taken := range limits.blocked {
		if start < taken.to && taken.from < reserved {
			return false
		}
	}
	return met == allRules
}
