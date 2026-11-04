package corpus

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func window(weekday, open, close int) Window {
	return Window{Weekday: weekday, Open: open, Close: close}
}
func doctor(name string, windows ...Window) Doctor {
	return Doctor{Name: name, Windows: windows}
}
func booking(day, start, end int, doctor string) Booking {
	return Booking{Day: day, Start: start, End: end, Doctor: doctor}
}
func at(index int) *int { return &index }
func weekOf(open, close int) []Window {
	windows := make([]Window, 5)
	for weekday := 0; weekday < 5; weekday++ {
		windows[weekday] = window(weekday, open, close)
	}
	return windows
}
func base() Request {
	return Request{
		NowDay:       100,
		NowMinute:    480,
		RequestedDay: 100,
		HorizonDays:  2,
		Kind:         "checkup",
		Doctors:      []Doctor{doctor("Ada", weekOf(540, 1020)...)},
	}
}
func traceSteps() []string {
	return []string{
		"normalised", "validated", "holiday-filter", "hours-and-lunch", "notice",
		"doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority",
		"earliest-grid-slot",
	}
}
func success(day, start, end int, name string) Outcome {
	return Outcome{Appointment: &Appointment{
		Day: day, Start: start, End: end, Doctor: name, Trace: traceSteps(),
	}}
}
func failure(code string, index *int) Outcome {
	return Outcome{Err: &ClinicError{Code: code, Index: index}}
}
func sameOutcome(one, other Outcome) bool {
	if (one.Err == nil) != (other.Err == nil) {
		return false
	}
	if (one.Appointment == nil) != (other.Appointment == nil) {
		return false
	}
	if one.Err != nil {
		return one.Err.Code == other.Err.Code && sameIndex(one.Err.Index, other.Err.Index)
	}
	mine, theirs := one.Appointment, other.Appointment
	if mine.Day != theirs.Day || mine.Start != theirs.Start || mine.End != theirs.End {
		return false
	}
	if mine.Doctor != theirs.Doctor || len(mine.Trace) != len(theirs.Trace) {
		return false
	}
	for index := range mine.Trace {
		if mine.Trace[index] != theirs.Trace[index] {
			return false
		}
	}
	return true
}
func sameIndex(one, other *int) bool {
	if one == nil || other == nil {
		return one == nil && other == nil
	}
	return *one == *other
}
func check(t *testing.T, given Request, want Outcome) {
	t.Helper()
	actual := Solution(given)
	if !sameOutcome(actual, want) {
		t.Fatalf("Solution(%+v) = %+v, want %+v", given, actual, want)
	}
	if brute := oracle(given); !sameOutcome(actual, brute) {
		t.Fatalf("Solution(%+v) = %+v, brute force = %+v", given, actual, brute)
	}
}

var oracleName = regexp.MustCompile(`^[a-z0-9 -]+$`)

func windowCovers(windows []Window, weekday, start, reserved int) bool {
	for _, each := range windows {
		if each.Weekday == weekday && each.Open <= start && reserved <= each.Close {
			return true
		}
	}
	return false
}
func overlapsAny(daily []Booking, start, reserved int) bool {
	for _, each := range daily {
		if start < each.End && each.Start < reserved {
			return true
		}
	}
	return false
}

// oracle reads the contract literally and inspects every candidate day, doctor
// and five-minute start, so it shares no scheduling shortcut with Solution.
func oracle(given Request) Outcome {
	kind := strings.ToLower(strings.Trim(given.Kind, " "))
	if kind != "checkup" && kind != "consultation" && kind != "procedure" {
		return failure("BAD_REQUEST", nil)
	}
	if given.NowDay < 0 || given.NowDay > 1_000_000 ||
		given.NowMinute < 0 || given.NowMinute > 1439 ||
		given.RequestedDay < 0 || given.RequestedDay > 1_000_000 ||
		given.HorizonDays < 0 || given.HorizonDays > 14 {
		return failure("BAD_REQUEST", nil)
	}
	if len(given.Doctors) < 1 || len(given.Doctors) > 12 {
		return failure("BAD_DOCTORS", nil)
	}
	keys := make([]string, len(given.Doctors))
	seenNames := map[string]bool{}
	for index, entry := range given.Doctors {
		key := strings.ToLower(strings.Trim(entry.Name, " "))
		keys[index] = key
		if !oracleName.MatchString(key) || seenNames[key] {
			return failure("BAD_DOCTORS", at(index))
		}
		seenNames[key] = true
	}
	for index, entry := range given.Doctors {
		if len(entry.Windows) > 8 {
			return failure("BAD_WINDOW", at(index))
		}
		for _, each := range entry.Windows {
			bad := each.Weekday < 0 || each.Weekday > 6 || each.Open < 0
			if bad || each.Open >= each.Close || each.Close > 1440 {
				return failure("BAD_WINDOW", at(index))
			}
		}
	}
	if len(given.Holidays) > 60 {
		return failure("BAD_HOLIDAY", nil)
	}
	closed := map[int]bool{}
	for index, day := range given.Holidays {
		if day < 0 || day > 1_000_000 || closed[day] {
			return failure("BAD_HOLIDAY", at(index))
		}
		closed[day] = true
	}
	if len(given.Bookings) > 200 {
		return failure("BAD_BOOKING", nil)
	}
	for index, each := range given.Bookings {
		key := strings.ToLower(strings.Trim(each.Doctor, " "))
		bad := each.Day < 0 || each.Day > 1_000_000 || each.Start < 0
		if bad || each.Start >= each.End || each.End > 1440 || !seenNames[key] {
			return failure("BAD_BOOKING", at(index))
		}
	}
	preferred := strings.ToLower(strings.Trim(given.PreferredDoctor, " "))
	if preferred != "" && !seenNames[preferred] {
		return failure("UNKNOWN_DOCTOR", nil)
	}
	if given.RequestedDay < given.NowDay || given.RequestedDay-given.NowDay > 8 {
		return failure("BAD_DAY_ORDER", nil)
	}
	duration, buffer := 20, 5
	if kind == "consultation" {
		duration, buffer = 30, 10
	}
	if kind == "procedure" {
		duration, buffer = 60, 15
	}
	last := given.RequestedDay + given.HorizonDays
	if last > given.RequestedDay+14 {
		last = given.RequestedDay + 14
	}
	if last > 1_000_000 {
		last = 1_000_000
	}
	type choice struct {
		day, start int
		key, name  string
	}
	found := []choice{}
	for day := given.RequestedDay; day <= last; day++ {
		if closed[day] {
			continue
		}
		weekday := day % 7
		open, shut := 540, 1020
		if weekday == 5 {
			open, shut = 600, 840
		}
		if weekday == 6 {
			open, shut = 0, 0
		}
		for index, entry := range given.Doctors {
			key := keys[index]
			if preferred != "" && !given.Urgent && key != preferred {
				continue
			}
			daily := []Booking{}
			for _, each := range given.Bookings {
				taken := strings.ToLower(strings.Trim(each.Doctor, " "))
				if each.Day == day && taken == key {
					daily = append(daily, each)
				}
			}
			if len(daily) >= 4 {
				continue
			}
			for start := 0; start <= 1435; start += 5 {
				reserved := start + duration + buffer
				if start < open || reserved > shut {
					continue
				}
				if start < 780 && reserved > 720 {
					continue
				}
				if day == given.NowDay && start < given.NowMinute+60 {
					continue
				}
				if !windowCovers(entry.Windows, weekday, start, reserved) {
					continue
				}
				if overlapsAny(daily, start, reserved) {
					continue
				}
				name := strings.Trim(entry.Name, " ")
				found = append(found, choice{day, start, key, name})
			}
		}
	}
	if len(found) == 0 {
		return failure("NO_SLOT", nil)
	}
	sort.Slice(found, func(i, j int) bool {
		left, right := found[i], found[j]
		if left.day != right.day {
			return left.day < right.day
		}
		if left.start != right.start {
			return left.start < right.start
		}
		if left.key != right.key {
			return left.key < right.key
		}
		return left.name < right.name
	})
	first := found[0]
	return success(first.day, first.start, first.start+duration, first.name)
}

func changed(mutate func(*Request)) Request {
	given := base()
	mutate(&given)
	return given
}

func TestClinicBookingHandComputedCases(t *testing.T) {
	check(t, base(), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) { r.Kind = "  CONSULTATION  " }),
		success(100, 540, 570, "Ada"))
	check(t, changed(func(r *Request) { r.NowMinute = 500 }), success(100, 560, 580, "Ada"))
	check(t, changed(func(r *Request) { r.NowMinute = 1000 }), success(101, 540, 560, "Ada"))
	check(t, changed(func(r *Request) { r.Kind = "consultation" }),
		success(100, 540, 570, "Ada"))
	check(t, changed(func(r *Request) { r.Kind = "procedure" }), success(100, 540, 600, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{doctor("  Ada  ", window(2, 600, 660))}
	}), success(100, 600, 620, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{doctor("Ada", window(2, 700, 840))}
	}), success(100, 780, 800, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 540, 570, "  ADA  ")}
	}), success(100, 570, 590, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 540, 565, "Ada")}
	}), success(100, 565, 585, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{
			booking(100, 540, 550, "Ada"), booking(100, 560, 570, "Ada"),
			booking(100, 580, 590, "Ada"), booking(100, 600, 610, "Ada"),
		}
	}), success(101, 540, 560, "Ada"))
	check(t, changed(func(r *Request) { r.Holidays = []int{100} }),
		success(101, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Bo", window(2, 540, 1020)),
			doctor("Ada", window(2, 540, 1020)),
		}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Zoe", window(2, 540, 1020)),
			doctor("Ada", window(2, 540, 1020)),
		}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("BO", window(2, 540, 1020)),
			doctor("ada", window(2, 540, 1020)),
		}
	}), success(100, 540, 560, "ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = make([]Doctor, 12)
		for number := range r.Doctors {
			name := "Doc " + strconv.Itoa(number)
			r.Doctors[number] = doctor(name, window(2, 540, 1020))
		}
	}), success(100, 540, 560, "Doc 0"))
}

func TestClinicBookingValidationErrors(t *testing.T) {
	cases := []struct {
		given Request
		want  Outcome
	}{
		{changed(func(r *Request) { r.NowDay = -1 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.RequestedDay = -1 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.NowMinute = 1440 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.NowMinute = -1 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.HorizonDays = 15 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.HorizonDays = -1 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.NowDay = 1_000_001 }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.RequestedDay = 1_000_001 }),
			failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.Kind = "other" }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.Kind = "" }), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) { r.Doctors = nil }), failure("BAD_DOCTORS", nil)},
		{changed(func(r *Request) {
			r.Doctors = nil
			for number := 0; number < 13; number++ {
				r.Doctors = append(r.Doctors, doctor("Doc"+strconv.Itoa(number)))
			}
		}), failure("BAD_DOCTORS", nil)},
		{changed(func(r *Request) { r.Doctors = []Doctor{doctor("Ada@")} }),
			failure("BAD_DOCTORS", at(0))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{
				doctor("Ada", window(7, 540, 600)),
				doctor(" ada "),
			}
		}), failure("BAD_DOCTORS", at(1))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada"), doctor("ada")}
			r.Holidays = []int{-1}
		}), failure("BAD_DOCTORS", at(1))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{
				doctor("Ada"), doctor("Bo"),
				doctor("Cy", window(2, 900, 900)),
			}
		}), failure("BAD_WINDOW", at(2))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada", window(2, 700, 700))}
			r.Holidays = []int{-1}
		}), failure("BAD_WINDOW", at(0))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada", window(2, 540, 1441))}
		}), failure("BAD_WINDOW", at(0))},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada", window(-1, 540, 600))}
		}), failure("BAD_WINDOW", at(0))},
		{changed(func(r *Request) {
			windows := make([]Window, 9)
			for number := range windows {
				windows[number] = window(2, 540, 600)
			}
			r.Doctors = []Doctor{doctor("Ada", windows...)}
		}), failure("BAD_WINDOW", at(0))},
		{changed(func(r *Request) { r.Holidays = []int{100, 100} }),
			failure("BAD_HOLIDAY", at(1))},
		{changed(func(r *Request) { r.Holidays = []int{1_000_001} }),
			failure("BAD_HOLIDAY", at(0))},
		{changed(func(r *Request) {
			r.Holidays = make([]int, 61)
			for number := range r.Holidays {
				r.Holidays[number] = 200 + number
			}
		}), failure("BAD_HOLIDAY", nil)},
		{changed(func(r *Request) {
			r.Holidays = []int{-1}
			r.Bookings = []Booking{booking(100, 540, 540, "Ada")}
		}), failure("BAD_HOLIDAY", at(0))},
		{changed(func(r *Request) {
			r.Bookings = []Booking{
				booking(100, 540, 550, "Ada"), booking(100, 540, 540, "Ada"),
			}
		}), failure("BAD_BOOKING", at(1))},
		{changed(func(r *Request) {
			r.Bookings = []Booking{
				booking(100, 540, 550, "Ada"), booking(100, 550, 560, "Ada"),
				booking(100, 560, 560, "Ada"),
			}
		}), failure("BAD_BOOKING", at(2))},
		{changed(func(r *Request) {
			r.Bookings = []Booking{booking(100, 540, 1441, "Ada")}
		}),
			failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) { r.Bookings = []Booking{booking(100, -1, 550, "Ada")} }),
			failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) { r.Bookings = []Booking{booking(-1, 540, 550, "Ada")} }),
			failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) {
			r.Bookings = []Booking{booking(1_000_001, 540, 550, "Ada")}
		}),
			failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) {
			r.Bookings = []Booking{booking(100, 540, 550, "Missing")}
		}),
			failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) {
			r.Bookings = make([]Booking, 201)
			for number := range r.Bookings {
				r.Bookings[number] = booking(500+number, 0, 1, "Ada")
			}
		}), failure("BAD_BOOKING", nil)},
		{changed(func(r *Request) {
			r.Bookings = []Booking{booking(100, 1, 1, "Ada")}
			r.PreferredDoctor = "Bo"
		}), failure("BAD_BOOKING", at(0))},
		{changed(func(r *Request) { r.PreferredDoctor = "Bo" }),
			failure("UNKNOWN_DOCTOR", nil)},
		{changed(func(r *Request) { r.PreferredDoctor = "Bo@" }),
			failure("UNKNOWN_DOCTOR", nil)},
		{changed(func(r *Request) { r.RequestedDay = 99 }), failure("BAD_DAY_ORDER", nil)},
		{changed(func(r *Request) { r.RequestedDay = 109 }), failure("BAD_DAY_ORDER", nil)},
		{changed(func(r *Request) {
			r.PreferredDoctor = "Bo"
			r.RequestedDay = 109
		}), failure("UNKNOWN_DOCTOR", nil)},
		{changed(func(r *Request) {
			r.Kind = "other"
			r.Doctors = nil
		}), failure("BAD_REQUEST", nil)},
		{changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada", window(1, 540, 1020))}
		}), failure("NO_SLOT", nil)},
		{changed(func(r *Request) { r.Doctors = []Doctor{doctor("Ada")} }),
			failure("NO_SLOT", nil)},
	}
	for _, one := range cases {
		check(t, one.given, one.want)
	}
}

func TestClinicBookingBoundaries(t *testing.T) {
	check(t, changed(func(r *Request) { r.NowMinute = 481 }), success(100, 545, 565, "Ada"))
	check(t, changed(func(r *Request) { r.NowMinute = 1439 }), success(101, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.NowDay, r.NowMinute, r.RequestedDay, r.HorizonDays = 0, 0, 0, 0
	}), success(0, 540, 560, "Ada"))
	check(t, changed(func(r *Request) { r.HorizonDays = 0 }), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.HorizonDays = 0
		r.Holidays = []int{100}
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) { r.HorizonDays = 14 }), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.HorizonDays = 14
		r.Holidays = nil
		for day := 100; day < 114; day++ {
			r.Holidays = append(r.Holidays, day)
		}
	}), success(114, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.RequestedDay = 108
		r.HorizonDays = 0
	}), success(108, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.RequestedDay = 103
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(5, 600, 840))}
	}), success(103, 600, 620, "Ada"))
	check(t, changed(func(r *Request) {
		r.RequestedDay = 103
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(5, 540, 1020))}
	}), success(103, 600, 620, "Ada"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{doctor("Ada", window(2, 540, 1440))}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.RequestedDay = 104
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(6, 540, 1020))}
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) {
		r.RequestedDay = 100
		r.HorizonDays = 2
		r.Doctors = []Doctor{doctor("Ada", window(6, 540, 1020))}
	}), failure("NO_SLOT", nil))
	for _, span := range [][2]int{{540, 565}, {600, 625}, {995, 1020}, {696, 900}} {
		expected := success(100, span[0], span[0]+20, "Ada")
		if span[0] == 600 {
			expected = success(100, 600, 620, "Ada")
		}
		if span[0] == 995 {
			expected = success(100, 995, 1015, "Ada")
		}
		if span[0] == 696 {
			expected = success(100, 780, 800, "Ada")
		}
		check(t, changed(func(r *Request) {
			r.Doctors = []Doctor{doctor("Ada", window(2, span[0], span[1]))}
		}), expected)
	}
	check(t, changed(func(r *Request) {
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(2, 540, 564))}
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{doctor("Ada", window(2, 720, 780))}
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 540, 695, "Ada")}
	}), success(100, 695, 715, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 540, 555, "Ada")}
	}), success(100, 555, 575, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 565, 575, "Ada")}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(2, 575, 600))}
		r.Bookings = []Booking{booking(100, 550, 575, "Ada")}
	}), success(100, 575, 595, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{
			booking(100, 800, 810, "Ada"), booking(100, 820, 830, "Ada"),
			booking(100, 840, 850, "Ada"),
		}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.HorizonDays = 0
		r.Doctors = []Doctor{doctor("Ada", window(2, 800, 900))}
		r.Bookings = []Booking{
			booking(100, 540, 550, "Ada"), booking(100, 560, 570, "Ada"),
			booking(100, 580, 590, "Ada"), booking(100, 600, 610, "Ada"),
		}
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Ada", window(2, 540, 1020)),
			doctor("Bo", window(2, 540, 1020)),
		}
		r.Bookings = []Booking{
			booking(100, 540, 550, "Ada"), booking(100, 560, 570, "Ada"),
			booking(100, 580, 590, "Ada"), booking(100, 600, 610, "Ada"),
		}
	}), success(100, 540, 560, "Bo"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Ada"),
			doctor("Bo", window(2, 540, 1020)),
		}
		r.PreferredDoctor = "Ada"
	}), failure("NO_SLOT", nil))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Bo", window(2, 540, 1020)),
			doctor("Ada", window(2, 540, 1020)),
		}
		r.PreferredDoctor = "Bo"
	}), success(100, 540, 560, "Bo"))
	check(t, changed(func(r *Request) {
		r.Doctors = []Doctor{
			doctor("Bo", window(2, 540, 1020)),
			doctor("Ada", window(2, 540, 1020)),
		}
		r.PreferredDoctor = "Bo"
		r.Urgent = true
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) { r.PreferredDoctor = " ada " }),
		success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.Bookings = []Booking{booking(100, 0, 1, "ada")}
	}), success(100, 540, 560, "Ada"))
	check(t, changed(func(r *Request) {
		r.NowDay = 999_992
		r.RequestedDay = 1_000_000
		r.HorizonDays = 14
	}), success(1_000_000, 540, 560, "Ada"))
}

func TestClinicBookingDomainLimits(t *testing.T) {
	eight := make([]Window, 8)
	for number := range eight {
		eight[number] = window(2, 540, 1020)
	}
	check(t, changed(func(r *Request) { r.Doctors = []Doctor{doctor("Ada", eight...)} }),
		success(100, 540, 560, "Ada"))
	holidays := make([]int, 60)
	for number := range holidays {
		holidays[number] = 200 + number
	}
	check(t, changed(func(r *Request) { r.Holidays = holidays }), success(100, 540, 560, "Ada"))
	bookings := make([]Booking, 200)
	for number := range bookings {
		bookings[number] = booking(500+number, 0, 1, "Ada")
	}
	check(t, changed(func(r *Request) { r.Bookings = bookings }), success(100, 540, 560, "Ada"))
	doctors := make([]Doctor, 12)
	for number := range doctors {
		doctors[number] = doctor("Doc "+strconv.Itoa(number), window(2, 540, 1020))
	}
	check(t, changed(func(r *Request) { r.Doctors = doctors }), success(100, 540, 560, "Doc 0"))
	packed := make([]Booking, 200)
	for number := range packed {
		packed[number] = booking(500+number, 0, 1, "Doc "+strconv.Itoa(number%12))
	}
	check(t, changed(func(r *Request) {
		r.HorizonDays = 14
		r.Doctors = doctors
		r.Holidays = holidays
		r.Bookings = packed
	}), success(100, 540, 560, "Doc 0"))
}

type splitMix64 struct{ state uint64 }

func (rng *splitMix64) next() uint64 {
	rng.state += 0x9e3779b97f4a7c15
	mixed := rng.state
	mixed = (mixed ^ (mixed >> 30)) * 0xbf58476d1ce4e5b9
	mixed = (mixed ^ (mixed >> 27)) * 0x94d049bb133111eb
	return mixed ^ (mixed >> 31)
}

type fixtures struct{ rng *splitMix64 }

func (f *fixtures) below(limit int) int {
	return int((f.rng.next() >> 16) % uint64(limit))
}
func (f *fixtures) between(low, high int) int   { return low + f.below(high-low+1) }
func (f *fixtures) pick(values []string) string { return values[f.below(len(values))] }
func (f *fixtures) spelled(name string) string {
	spelled := name
	if f.below(3) == 0 {
		spelled = strings.ToLower(spelled)
	}
	if f.below(4) == 0 {
		spelled = " " + spelled + " "
	}
	return spelled
}
func (f *fixtures) kind() string {
	kind := f.pick([]string{"checkup", "consultation", "procedure"})
	if f.below(4) == 0 {
		kind = strings.ToUpper(kind)
	}
	if f.below(4) == 0 {
		kind = " " + kind + "  "
	}
	return kind
}
func (f *fixtures) windows() []Window {
	windows := []Window{}
	for weekday := 0; weekday < 7; weekday++ {
		if f.below(4) == 0 {
			continue
		}
		open, shut := 540, 1020
		if weekday == 5 {
			open, shut = 600, 840
		}
		if f.below(5) == 0 {
			open = []int{600, 660, 690, 696, 700, 720, 760}[f.below(7)]
		}
		if open >= shut {
			continue
		}
		windows = append(windows, window(weekday, open, shut))
	}
	return windows
}
func (f *fixtures) bookings(names []string, first, last int) []Booking {
	bookings := []Booking{}
	for count := f.below(6); count > 0; count-- {
		name := f.pick(names)
		day := f.between(first, last)
		start := 540 + 5*f.below(80)
		length := []int{5, 10, 15, 20, 30, 45}[f.below(6)]
		bookings = append(bookings, booking(day, start, start+length, f.spelled(name)))
		if f.below(3) == 0 {
			touching := start + length
			bookings = append(bookings, booking(day, touching, touching+10, name))
		}
	}
	if f.below(4) == 0 {
		name := f.pick(names)
		day := f.between(first, last)
		for slot := 0; slot < 4; slot++ {
			start := 800 + 10*slot
			bookings = append(bookings, booking(day, start, start+5, name))
		}
	}
	return bookings
}
func (f *fixtures) request() Request {
	nowDay := f.between(20, 900)
	offset := f.below(9)
	horizon := f.below(15)
	first := nowDay + offset
	last := first + horizon
	names := []string{"Ada", "Bo", "Cy", "Dee"}[:f.between(1, 4)]
	doctors := make([]Doctor, len(names))
	for index, name := range names {
		doctors[index] = doctor(f.spelled(name), f.windows()...)
	}
	preferred := ""
	if f.below(2) == 0 {
		preferred = f.spelled(f.pick(names))
	}
	closed := map[int]bool{}
	holidays := []int{}
	for count := f.below(3); count > 0; count-- {
		day := f.between(first, last)
		if !closed[day] {
			closed[day] = true
			holidays = append(holidays, day)
		}
	}
	sort.Ints(holidays)
	return Request{
		NowDay:          nowDay,
		NowMinute:       f.below(1440),
		RequestedDay:    first,
		HorizonDays:     horizon,
		Kind:            f.kind(),
		Urgent:          f.below(2) == 0,
		PreferredDoctor: preferred,
		Holidays:        holidays,
		Doctors:         doctors,
		Bookings:        f.bookings(names, first, last),
	}
}
func (f *fixtures) probe() Request {
	given := f.request()
	first := given.RequestedDay
	switch f.below(6) {
	case 0:
		name := given.Doctors[0].Name
		for slot := 0; slot < 4; slot++ {
			start := 540 + 10*slot
			given.Bookings = append(
				given.Bookings,
				booking(first, start, start+5, name),
			)
		}
	case 1:
		weekday := (first + given.HorizonDays) % 7
		if weekday < 5 {
			given.Doctors = []Doctor{doctor("Solo", window(weekday, 540, 1020))}
		}
	case 2:
		given.Doctors = []Doctor{doctor("Ada", window(2, 696, 900))}
		given.NowDay, given.RequestedDay = 100, 100
		given.HorizonDays, given.Bookings = 0, nil
	case 3:
		given.Bookings = []Booking{booking(first, 540, 695, given.Doctors[0].Name)}
		given.HorizonDays = 0
	case 4:
		given.Doctors = []Doctor{doctor("Ada")}
		given.Bookings = nil
	case 5:
		given.Doctors = []Doctor{doctor("Ada", window(6, 540, 1020))}
	}
	return given
}
func (f *fixtures) invalid() Request {
	given := f.request()
	switch f.below(8) {
	case 0:
		given.HorizonDays = 15
	case 1:
		given.Doctors = append(given.Doctors, given.Doctors[0])
	case 2:
		if len(given.Doctors[0].Windows) == 0 {
			given.Doctors[0].Windows = []Window{window(2, 540, 1020)}
		}
		given.Doctors[0].Windows[0].Close = 1441
	case 3:
		given.Holidays = append(given.Holidays, 1_000_001)
	case 4:
		given.Bookings = append(
			given.Bookings,
			booking(100, 540, 1441, given.Doctors[0].Name),
		)
	case 5:
		given.Bookings = append(
			given.Bookings,
			booking(given.RequestedDay, 540, 550, "Nobody"),
		)
	case 6:
		given.PreferredDoctor = "Zed"
	default:
		given.RequestedDay = given.NowDay - 1 - f.below(4)
	}
	return given
}

func TestClinicBookingSeededRandom(t *testing.T) {
	const total = 2400
	f := &fixtures{rng: &splitMix64{state: 20261017}}
	kinds := map[string]bool{}
	answering := map[string]bool{}
	codes := map[string]bool{}
	valid, invalid, laterDay, shifted, drawn, drawnValid := 0, 0, 0, 0, 0, 0
	for round := 0; round < total; round++ {
		given := f.request()
		drawn++
		derived := false
		if f.below(5) == 0 {
			given = f.probe()
			derived = true
		}
		if f.below(8) == 0 {
			given = f.invalid()
			derived = true
		}
		want := oracle(given)
		if want.Err == nil {
			valid++
			if !derived {
				drawnValid++
			}
			kinds[strings.ToLower(strings.Trim(given.Kind, " "))] = true
			answering[want.Appointment.Doctor] = true
			if want.Appointment.Day > given.RequestedDay {
				laterDay++
			}
			if want.Appointment.Start > 540 {
				shifted++
			}
		} else {
			invalid++
			codes[want.Err.Code] = true
		}
		check(t, given, want)
	}
	if valid*2 < total {
		t.Fatalf("valid request ratio below 50%%: %d/%d", valid, total)
	}
	if drawnValid*2 < total {
		t.Fatalf("truly random valid share below 50%%: %d/%d of %d drawn",
			drawnValid, total, drawn)
	}
	if invalid == 0 {
		t.Fatalf("generator produced no invalid requests")
	}
	for _, kind := range []string{"checkup", "consultation", "procedure"} {
		if !kinds[kind] {
			t.Fatalf("kind not covered: %s", kind)
		}
	}
	for _, code := range []string{
		"BAD_REQUEST", "BAD_DOCTORS", "BAD_WINDOW", "BAD_HOLIDAY",
		"BAD_BOOKING", "UNKNOWN_DOCTOR", "BAD_DAY_ORDER", "NO_SLOT",
	} {
		if !codes[code] {
			t.Fatalf("error code not covered: %s", code)
		}
	}
	if laterDay == 0 || shifted == 0 {
		t.Fatalf("answers never moved past the first grid slot: later=%d shifted=%d",
			laterDay, shifted)
	}
	if len(answering) < 2 {
		t.Fatalf("only one doctor ever chosen: %v", answering)
	}
	t.Logf(
		"seeded mix: valid=%d invalid=%d drawn=%d drawn_valid=%d kinds=%v "+
			"doctors=%v errors=%v later_days=%d shifted_starts=%d",
		valid, invalid, drawn, drawnValid, kinds, answering, codes, laterDay, shifted,
	)
}
