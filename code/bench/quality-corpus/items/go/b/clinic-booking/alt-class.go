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
type appointmentKind struct {
	name             string
	duration, buffer int
}
type clinicDoctor struct {
	record Doctor
	key    string
}
type interval struct{ start, end int }
type daySchedule struct {
	occupied []interval
	opens    int
}
type clinic struct {
	request   Request
	kind      appointmentKind
	doctors   []clinicDoctor
	closed    map[int]bool
	preferred string
}
type slot struct {
	day, start int
	doctor     clinicDoctor
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
	gridMinutes     = 5
)

var className = regexp.MustCompile(`^[A-Za-z0-9 -]+$`)
var classKinds = []appointmentKind{
	{"checkup", 20, 5}, {"consultation", 30, 10}, {"procedure", 60, 15},
}
var classHours = [7][2]int{
	{540, 1020}, {540, 1020}, {540, 1020}, {540, 1020},
	{540, 1020}, {600, 840}, {0, 0},
}
var classTrace = []string{
	"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
	"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
	"earliest-grid-slot",
}

// Solution builds a validated clinic before asking it to reserve an interval.
func Solution(request Request) Outcome {
	place, issue := newClinic(request)
	if issue != nil {
		return Outcome{Err: issue}
	}
	last := place.request.RequestedDay + place.request.HorizonDays
	if last > maximumDay {
		last = maximumDay
	}
	for day := place.request.RequestedDay; day <= last; day++ {
		if !place.closed[day] {
			if found := place.findOnDay(day); found != nil {
				return Outcome{Appointment: place.makeAppointment(*found)}
			}
		}
	}
	return Outcome{Err: &ClinicError{Code: "NO_SLOT"}}
}

func newClinic(request Request) (*clinic, *ClinicError) {
	request = normalizeClinicRequest(request)
	kind, known := clinicKind(strings.ToLower(strings.Trim(request.Kind, " ")))
	if issue := validateClinicRequest(request, known); issue != nil {
		return nil, issue
	}
	return &clinic{
		request: request, kind: kind, doctors: sortedDoctors(request.Doctors),
		closed:    closedDays(request.Holidays),
		preferred: strings.ToLower(request.PreferredDoctor),
	}, nil
}

func sortedDoctors(records []Doctor) []clinicDoctor {
	doctors := make([]clinicDoctor, len(records))
	for index, doctor := range records {
		doctors[index] = clinicDoctor{record: doctor, key: strings.ToLower(doctor.Name)}
	}
	sort.Slice(doctors, func(i, j int) bool { return doctors[i].key < doctors[j].key })
	return doctors
}

func closedDays(days []int) map[int]bool {
	closed := make(map[int]bool, len(days))
	for _, day := range days {
		closed[day] = true
	}
	return closed
}

func normalizeClinicRequest(request Request) Request {
	request.PreferredDoctor = strings.Trim(request.PreferredDoctor, " ")
	request.Doctors = append([]Doctor(nil), request.Doctors...)
	request.Bookings = append([]Booking(nil), request.Bookings...)
	for index := range request.Doctors {
		request.Doctors[index].Name = strings.Trim(request.Doctors[index].Name, " ")
	}
	for index := range request.Bookings {
		name := strings.Trim(request.Bookings[index].Doctor, " ")
		if !className.MatchString(name) {
			name = ""
		}
		request.Bookings[index].Doctor = name
	}
	return request
}

func clinicKind(name string) (appointmentKind, bool) {
	for _, kind := range classKinds {
		if kind.name == name {
			return kind, true
		}
	}
	return appointmentKind{}, false
}

func validateClinicRequest(request Request, knownKind bool) *ClinicError {
	if !knownKind || !clinicNumbersValid(request) {
		return &ClinicError{Code: "BAD_REQUEST"}
	}
	if issue := validateClinicDoctors(request.Doctors); issue != nil {
		return issue
	}
	if issue := validateClinicWindows(request.Doctors); issue != nil {
		return issue
	}
	if issue := validateClinicHolidays(request.Holidays); issue != nil {
		return issue
	}
	if issue := validateClinicBookings(request); issue != nil {
		return issue
	}
	return validateClinicOrder(request)
}

func clinicNumbersValid(request Request) bool {
	return request.NowDay >= 0 && request.NowDay <= maximumDay &&
		request.RequestedDay >= 0 && request.RequestedDay <= maximumDay &&
		request.NowMinute >= 0 && request.NowMinute <= 1439 &&
		request.HorizonDays >= 0 && request.HorizonDays <= maximumHorizon
}

func validateClinicDoctors(doctors []Doctor) *ClinicError {
	if len(doctors) < 1 || len(doctors) > 12 {
		return &ClinicError{Code: "BAD_DOCTORS"}
	}
	seen := map[string]bool{}
	for index, doctor := range doctors {
		if !className.MatchString(doctor.Name) {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &index}
		}
		key := strings.ToLower(doctor.Name)
		if seen[key] {
			return &ClinicError{Code: "BAD_DOCTORS", Index: &index}
		}
		seen[key] = true
	}
	return nil
}

func validateClinicWindows(doctors []Doctor) *ClinicError {
	for index, doctor := range doctors {
		if len(doctor.Windows) > 8 {
			return &ClinicError{Code: "BAD_WINDOW", Index: &index}
		}
		for _, window := range doctor.Windows {
			badDay := window.Weekday < 0 || window.Weekday > 6
			badTime := window.Open < 0 || window.Open >= window.Close ||
				window.Close > 1440
			if badDay || badTime {
				return &ClinicError{Code: "BAD_WINDOW", Index: &index}
			}
		}
	}
	return nil
}

func validateClinicHolidays(days []int) *ClinicError {
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

func validateClinicBookings(request Request) *ClinicError {
	if len(request.Bookings) > 200 {
		return &ClinicError{Code: "BAD_BOOKING"}
	}
	known := make(map[string]bool, len(request.Doctors))
	for _, doctor := range request.Doctors {
		known[strings.ToLower(doctor.Name)] = true
	}
	for index, booking := range request.Bookings {
		if booking.Day < 0 || booking.Day > maximumDay || booking.Start < 0 ||
			booking.Start >= booking.End || booking.End > 1440 ||
			!known[strings.ToLower(booking.Doctor)] {
			return &ClinicError{Code: "BAD_BOOKING", Index: &index}
		}
	}
	return nil
}

func validateClinicOrder(request Request) *ClinicError {
	preferred := strings.ToLower(request.PreferredDoctor)
	if request.PreferredDoctor != "" {
		found := false
		for _, doctor := range request.Doctors {
			found = found || strings.ToLower(doctor.Name) == preferred
		}
		if !found || !className.MatchString(request.PreferredDoctor) {
			return &ClinicError{Code: "UNKNOWN_DOCTOR"}
		}
	}
	if request.RequestedDay < request.NowDay || request.RequestedDay-request.NowDay > 8 {
		return &ClinicError{Code: "BAD_DAY_ORDER"}
	}
	return nil
}

func (place *clinic) findOnDay(day int) *slot {
	hours := classHours[day%7]
	var best *slot
	for _, doctor := range place.availableDoctors() {
		schedule := place.scheduleFor(doctor, day)
		if len(schedule.occupied) >= maximumDaily {
			continue
		}
		start, found := schedule.firstFit(place, doctor, day, hours[1])
		if !found {
			continue
		}
		if best == nil || start < best.start {
			best = &slot{day: day, start: start, doctor: doctor}
		}
	}
	return best
}

func (place *clinic) availableDoctors() []clinicDoctor {
	rows := make([]clinicDoctor, 0, len(place.doctors))
	for _, doctor := range place.doctors {
		if place.request.Urgent || place.preferred == "" || doctor.key == place.preferred {
			rows = append(rows, doctor)
		}
	}
	return rows
}

func (place *clinic) scheduleFor(doctor clinicDoctor, day int) daySchedule {
	opens := classHours[day%7][0]
	if day == place.request.NowDay && opens < place.request.NowMinute+minimumNotice {
		opens = place.request.NowMinute + minimumNotice
	}
	schedule := daySchedule{occupied: make([]interval, 0, maximumDaily), opens: opens}
	for _, booking := range place.request.Bookings {
		if booking.Day == day && strings.ToLower(booking.Doctor) == doctor.key {
			schedule.occupied = append(schedule.occupied, interval{
				booking.Start, booking.End,
			})
		}
	}
	return schedule
}

func (schedule daySchedule) firstFit(
	place *clinic, doctor clinicDoctor, day, closes int,
) (int, bool) {
	weekday := day % 7
	first := (schedule.opens + gridMinutes - 1) / gridMinutes * gridMinutes
	for start := first; start <= lastStart; start += gridMinutes {
		reservedEnd := start + place.kind.duration + place.kind.buffer
		if reservedEnd <= closes && (start >= lunchEnds || reservedEnd <= lunchBegins) &&
			doctorCovers(doctor.record.Windows, weekday, start, reservedEnd) &&
			schedule.intervalFree(start, reservedEnd) {
			return start, true
		}
	}
	return 0, false
}

func doctorCovers(windows []Window, weekday, start, reservedEnd int) bool {
	for _, window := range windows {
		if window.Weekday == weekday && window.Open <= start &&
			reservedEnd <= window.Close {
			return true
		}
	}
	return false
}

func (schedule daySchedule) intervalFree(start, end int) bool {
	for _, occupied := range schedule.occupied {
		if start < occupied.end && occupied.start < end {
			return false
		}
	}
	return true
}

func (place *clinic) makeAppointment(found slot) *Appointment {
	return &Appointment{
		Day: found.day, Start: found.start, End: found.start + place.kind.duration,
		Doctor: found.doctor.record.Name, Trace: append([]string(nil), classTrace...),
	}
}
