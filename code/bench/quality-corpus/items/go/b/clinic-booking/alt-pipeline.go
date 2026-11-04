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
type appointmentRule struct{ duration, buffer int }
type slotChoice struct {
	day, start int
	doctor     Doctor
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
)

var pipelineName = regexp.MustCompile(`^[A-Za-z0-9 -]+$`)
var pipelineKinds = map[string]appointmentRule{
	"checkup": {20, 5}, "consultation": {30, 10}, "procedure": {60, 15},
}
var pipelineHours = [7][2]int{
	{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
	{540, 1020}, {600, 840}, {0, 0},
}
var pipelineTrace = []string{
	"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
	"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
	"earliest-grid-slot",
}

// Solution validates a copied request, then selects the first surviving choice.
func Solution(request Request) Outcome {
	clean := normalize(request)
	if issue := validate(clean); issue != nil {
		return Outcome{Err: issue}
	}
	choices := candidateChoices(clean)
	if found := firstAllowed(clean, choices); found != nil {
		return Outcome{Appointment: found}
	}
	return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
}

func normalize(request Request) Request {
	request.Kind = strings.ToLower(strings.Trim(request.Kind, " "))
	request.PreferredDoctor = strings.Trim(request.PreferredDoctor, " ")
	request.Doctors = append([]Doctor(nil), request.Doctors...)
	request.Bookings = append([]Booking(nil), request.Bookings...)
	for index := range request.Doctors {
		request.Doctors[index].Name = strings.Trim(request.Doctors[index].Name, " ")
	}
	for index := range request.Bookings {
		request.Bookings[index].Doctor = strings.Trim(request.Bookings[index].Doctor, " ")
	}
	return request
}

func validate(request Request) *ClinicError {
	if issue := validateRequest(request); issue != nil {
		return issue
	}
	if issue := validateDoctors(request.Doctors); issue != nil {
		return issue
	}
	if issue := validateWindows(request.Doctors); issue != nil {
		return issue
	}
	if issue := validateHolidays(request.Holidays); issue != nil {
		return issue
	}
	if issue := validateBookings(request); issue != nil {
		return issue
	}
	return validatePreference(request)
}

func validateRequest(request Request) *ClinicError {
	if request.NowDay < 0 || request.NowDay > maximumDay ||
		request.RequestedDay < 0 || request.RequestedDay > maximumDay ||
		request.NowMinute < 0 || request.NowMinute > 1439 ||
		request.HorizonDays < 0 || request.HorizonDays > maximumHorizon {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if _, known := pipelineKinds[request.Kind]; !known {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	return nil
}

// pipelineKey is the lowercase name, or "" when the name is not valid.
func pipelineKey(name string) string {
	valid := pipelineName.MatchString(name)
	if !valid {
		return ""
	}
	return strings.ToLower(name)
}

func validateDoctors(doctors []Doctor) *ClinicError {
	if len(doctors) < 1 || len(doctors) > 12 {
		return &ClinicError{Code: "BAD_DOCTORS"}
	}
	seen := make(map[string]bool, len(doctors))
	for index, doctor := range doctors {
		key := pipelineKey(doctor.Name)
		if key == "" || seen[key] {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &index}
		}
		seen[key] = true
	}
	return nil
}

func validateWindows(doctors []Doctor) *ClinicError {
	for index, doctor := range doctors {
		if len(doctor.Windows) > 8 {
			return &ClinicError{Code: "BAD_WINDOW", Index: &index}
		}
		for _, window := range doctor.Windows {
			if window.Weekday < 0 || window.Weekday > 6 || window.Open < 0 ||
				window.Open >= window.Close || window.Close > 1440 {
				return &ClinicError{Code: "BAD_WINDOW", Index: &index}
			}
		}
	}
	return nil
}

func validateHolidays(days []int) *ClinicError {
	if len(days) > maximumHolidays {
		return &ClinicError{Code: "BAD_HOLIDAY"}
	}
	seen := make(map[int]bool, len(days))
	for index, day := range days {
		if day < 0 || day > maximumDay || seen[day] {
			return &ClinicError{Code: "BAD_HOLIDAY", Index: &index}
		}
		seen[day] = true
	}
	return nil
}

func validateBookings(request Request) *ClinicError {
	if len(request.Bookings) > 200 {
		return &ClinicError{Code: "BAD_BOOKING"}
	}
	known := make(map[string]bool, len(request.Doctors))
	for _, doctor := range request.Doctors {
		known[pipelineKey(doctor.Name)] = true
	}
	for index, booking := range request.Bookings {
		key := pipelineKey(booking.Doctor)
		if !bookingInBounds(booking) || key == "" || !known[key] {
			return &ClinicError{Code: "BAD_BOOKING", Index: &index}
		}
	}
	return nil
}

func bookingInBounds(booking Booking) bool {
	return booking.Day >= 0 && booking.Day <= maximumDay && booking.Start >= 0 &&
		booking.Start < booking.End && booking.End <= 1440
}

func validatePreference(request Request) *ClinicError {
	if request.PreferredDoctor != "" {
		key := pipelineKey(request.PreferredDoctor)
		found := false
		for _, doctor := range request.Doctors {
			found = found || pipelineKey(doctor.Name) == key
		}
		if key == "" || !found {
			return &ClinicError{Code: "UNKNOWN_DOCTOR"}
		}
	}
	if request.RequestedDay < request.NowDay || request.RequestedDay-request.NowDay > 8 {
		return &ClinicError{Code: "BAD_DAY_ORDER"}
	}
	return nil
}

func candidateChoices(request Request) []slotChoice {
	days := candidateDays(request)
	doctors := orderedEligibleDoctors(request)
	choices := make([]slotChoice, 0, 288*len(days)*len(doctors))
	for _, day := range days {
		choices = append(choices, choicesOnDay(day, doctors)...)
	}
	return choices
}

func candidateDays(request Request) []int {
	last := request.RequestedDay + request.HorizonDays
	if last > maximumDay {
		last = maximumDay
	}
	closed := make(map[int]bool, len(request.Holidays))
	for _, day := range request.Holidays {
		closed[day] = true
	}
	days := make([]int, 0, last-request.RequestedDay+1)
	for day := request.RequestedDay; day <= last; day++ {
		if !closed[day] {
			days = append(days, day)
		}
	}
	return days
}

func choicesOnDay(day int, doctors []Doctor) []slotChoice {
	choices := make([]slotChoice, 0, 288*len(doctors))
	for start := 0; start <= lastStart; start += 5 {
		for _, doctor := range doctors {
			choices = append(choices, slotChoice{
				day: day, start: start, doctor: doctor,
			})
		}
	}
	return choices
}

func orderedEligibleDoctors(request Request) []Doctor {
	ordered := make([]Doctor, 0, len(request.Doctors))
	preferred := strings.ToLower(request.PreferredDoctor)
	for _, doctor := range request.Doctors {
		if request.Urgent || preferred == "" || strings.ToLower(doctor.Name) == preferred {
			ordered = append(ordered, doctor)
		}
	}
	sort.Slice(ordered, func(i, j int) bool {
		return strings.ToLower(ordered[i].Name) < strings.ToLower(ordered[j].Name)
	})
	return ordered
}

func firstAllowed(request Request, choices []slotChoice) *Appointment {
	for _, choice := range choices {
		if passesClinicHours(request, choice) && passesDoctorWindow(request, choice) &&
			passesBookingLimits(request, choice) {
			return makeAppointment(request, choice)
		}
	}
	return nil
}

func passesClinicHours(request Request, choice slotChoice) bool {
	rule := pipelineKinds[request.Kind]
	reserved := choice.start + rule.duration + rule.buffer
	weekday := choice.day % 7
	hours := pipelineHours[weekday]
	open := choice.start >= hours[0] && reserved <= hours[1]
	clearOfLunch := choice.start >= lunchEnds || reserved <= lunchBegins
	noticeMet := choice.day != request.NowDay || choice.start >= request.NowMinute+minimumNotice
	return open && clearOfLunch && noticeMet
}

func passesDoctorWindow(request Request, choice slotChoice) bool {
	rule := pipelineKinds[request.Kind]
	reserved := choice.start + rule.duration + rule.buffer
	weekday := choice.day % 7
	for _, window := range choice.doctor.Windows {
		if window.Weekday == weekday && window.Open <= choice.start &&
			reserved <= window.Close {
			return true
		}
	}
	return false
}

func passesBookingLimits(request Request, choice slotChoice) bool {
	rule := pipelineKinds[request.Kind]
	reserved := choice.start + rule.duration + rule.buffer
	key := strings.ToLower(choice.doctor.Name)
	count := 0
	for _, booking := range request.Bookings {
		if booking.Day != choice.day || strings.ToLower(booking.Doctor) != key {
			continue
		}
		if choice.start < booking.End && booking.Start < reserved {
			return false
		}
		count++
	}
	return count < maximumDaily
}

func makeAppointment(request Request, choice slotChoice) *Appointment {
	rule := pipelineKinds[request.Kind]
	return &Appointment{
		Day: choice.day, Start: choice.start, End: choice.start + rule.duration,
		Doctor: choice.doctor.Name, Trace: append([]string(nil), pipelineTrace...),
	}
}
