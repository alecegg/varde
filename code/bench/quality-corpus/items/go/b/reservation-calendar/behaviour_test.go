package corpus

import (
	"fmt"
	"math/rand"
	"sort"
	"testing"
	"time"
)

func referenceAvailable(slots []Slot, reserved []Reservation) []string {
	open := make([]Slot, 0, len(slots))
	for _, slot := range slots {
		blocked := false
		for _, reservation := range reserved {
			if reservation.Start < slot.End && slot.Start < reservation.End {
				blocked = true
			}
		}
		if !blocked {
			open = append(open, slot)
		}
	}
	sort.Slice(open, func(left, right int) bool {
		if open[left].Start != open[right].Start {
			return open[left].Start < open[right].Start
		}
		return open[left].ID < open[right].ID
	})
	ids := make([]string, 0, len(open))
	for _, slot := range open {
		ids = append(ids, slot.ID)
	}
	return ids
}

func sameIDs(got, want []string) bool {
	if got == nil {
		return false
	}
	if len(got) != len(want) {
		return false
	}
	for index := range got {
		if got[index] != want[index] {
			return false
		}
	}
	return true
}

func TestReservationCalendarBankCases(t *testing.T) {
	cases := []struct {
		slots    []Slot
		reserved []Reservation
		want     []string
	}{
		{nil, nil, []string{}},
		{[]Slot{{"A", 540, 600}}, nil, []string{"A"}},
		{[]Slot{{"A", 540, 600}}, []Reservation{{540, 600}}, []string{}},
		{
			[]Slot{{"A", 480, 540}, {"B", 540, 600}},
			[]Reservation{{540, 570}},
			[]string{"A"},
		},
		{[]Slot{{"A", 540, 600}}, []Reservation{{570, 630}}, []string{}},
		{
			[]Slot{{"B", 600, 660}, {"A", 540, 600}},
			[]Reservation{{700, 720}},
			[]string{"A", "B"},
		},
		{[]Slot{{"B", 540, 600}, {"A", 540, 600}}, nil, []string{"A", "B"}},
		{[]Slot{{"é", 540, 600}, {"z", 540, 600}}, nil, []string{"z", "é"}},
		{
			[]Slot{{"A", 0, 30}, {"B", 1410, 1440}},
			[]Reservation{{30, 60}},
			[]string{"A", "B"},
		},
	}
	for _, testCase := range cases {
		got, err := solution(Request{Slots: testCase.slots, Reserved: testCase.reserved})
		if err != nil {
			t.Fatalf("solution(%v, %v) returned %v", testCase.slots, testCase.reserved, err)
		}
		if !sameIDs(got, testCase.want) {
			t.Fatalf("solution(%v, %v) = %v, want %v", testCase.slots, testCase.reserved, got, testCase.want)
		}
	}
}

func TestReservationCalendarRejectedRequests(t *testing.T) {
	cases := []struct {
		slots    []Slot
		reserved []Reservation
	}{
		{[]Slot{{"A", 600, 600}}, nil},
		{[]Slot{{"A", 640, 600}}, nil},
		{[]Slot{{"A", -30, 0}}, nil},
		{[]Slot{{"A", 1400, 1500}}, nil},
		{[]Slot{{"A", 540, 600}}, []Reservation{{800, 800}}},
		{[]Slot{{"A", 0, 1440}}, []Reservation{{900, 800}}},
		{[]Slot{{"A", 0, 1440}}, []Reservation{{-60, 60}}},
		{[]Slot{{"A", 0, 1440}}, []Reservation{{1380, 1500}}},
		{[]Slot{{"ok", 0, 30}, {"bad", 120, 60}}, nil},
		{[]Slot{{"A", -30, -10}}, nil},
		{[]Slot{{"A", 1500, 1600}}, nil},
		{[]Slot{{"A", 0, 1440}}, []Reservation{{-90, -60}}},
		{[]Slot{{"A", 0, 1440}}, []Reservation{{1500, 1600}}},
	}
	for _, testCase := range cases {
		got, err := solution(Request{Slots: testCase.slots, Reserved: testCase.reserved})
		if err == nil {
			t.Fatalf("solution(%v, %v) = %v, want invalid_interval", testCase.slots, testCase.reserved, got)
		}
		if err.Error() != "invalid_interval" {
			t.Fatalf("solution(%v, %v) error = %q, want invalid_interval", testCase.slots, testCase.reserved, err)
		}
		if got != nil {
			t.Fatalf("solution(%v, %v) = %v, want no identifiers", testCase.slots, testCase.reserved, got)
		}
	}
}

func TestReservationCalendarTouchingEndpoints(t *testing.T) {
	slots := []Slot{{"A", 0, 60}, {"B", 60, 120}, {"C", 120, 180}}
	reserved := []Reservation{{60, 120}}
	got, err := solution(Request{Slots: slots, Reserved: reserved})
	if err != nil {
		t.Fatalf("solution returned %v", err)
	}
	if !sameIDs(got, []string{"A", "C"}) {
		t.Fatalf("solution = %v, want [A C]", got)
	}
}

func TestReservationCalendarOrdering(t *testing.T) {
	slots := []Slot{{"D", 600, 630}, {"C", 540, 570}, {"B", 540, 570}, {"A", 480, 510}}
	got, err := solution(Request{Slots: slots})
	if err != nil {
		t.Fatalf("solution returned %v", err)
	}
	if !sameIDs(got, []string{"A", "B", "C", "D"}) {
		t.Fatalf("solution = %v, want [A B C D]", got)
	}
	siblings := []Slot{{"a", 540, 570}, {"AB", 540, 570}, {"A", 540, 570}, {"Aa", 540, 570}}
	got, err = solution(Request{Slots: siblings})
	if err != nil {
		t.Fatalf("solution returned %v", err)
	}
	if !sameIDs(got, []string{"A", "AB", "Aa", "a"}) {
		t.Fatalf("solution = %v, want [A AB Aa a]", got)
	}
}

func TestReservationCalendarLargeInput(t *testing.T) {
	generator := rand.New(rand.NewSource(20261017))
	slots := make([]Slot, 0, 3000)
	for index := 0; index < 3000; index++ {
		start := generator.Intn(1300)
		length := 10 + generator.Intn(60)
		slots = append(slots, Slot{fmt.Sprintf("S%04d", index), start, start + length})
	}
	reserved := make([]Reservation, 0, 60)
	for index := 0; index < 60; index++ {
		start := generator.Intn(1300)
		length := 5 + generator.Intn(16)
		reserved = append(reserved, Reservation{start, start + length})
	}
	generator.Shuffle(len(slots), func(left, right int) {
		slots[left], slots[right] = slots[right], slots[left]
	})
	starts := make([]int, 0, len(slots))
	for _, slot := range slots {
		starts = append(starts, slot.Start)
	}
	if sort.IntsAreSorted(starts) {
		t.Fatal("the large case must start in scrambled start order")
	}
	got, err := solution(Request{Slots: slots, Reserved: reserved})
	if err != nil {
		t.Fatalf("solution(large) returned %v", err)
	}
	want := referenceAvailable(slots, reserved)
	if !sameIDs(got, want) {
		t.Fatalf("solution(large) = %v, want %v", got, want)
	}
	if len(got) == 0 {
		t.Fatal("the large case must leave some slots available")
	}
	for index := 1; index < len(got); index++ {
		if got[index-1] == got[index] {
			t.Fatalf("solution(large) repeated identifier %q", got[index])
		}
	}
}

func TestReservationCalendarRandomisedRequests(t *testing.T) {
	generator := rand.New(rand.NewSource(11))
	for round := 0; round < 1500; round++ {
		slots := make([]Slot, 0, 6)
		reserved := make([]Reservation, 0, 4)
		for index := 0; index < generator.Intn(7); index++ {
			start := generator.Intn(1440)
			slots = append(slots, Slot{fmt.Sprintf("s%02d", index), start, start + 1 + generator.Intn(120)})
		}
		for index := 0; index < generator.Intn(5); index++ {
			start := generator.Intn(1439)
			reserved = append(reserved, Reservation{start, start + 1 + generator.Intn(120)})
		}
		valid := true
		for _, slot := range slots {
			if slot.End > 1440 {
				valid = false
			}
		}
		for _, reservation := range reserved {
			if reservation.End > 1440 {
				valid = false
			}
		}
		got, err := solution(Request{Slots: slots, Reserved: reserved})
		if !valid {
			if err == nil {
				t.Fatalf("round %d: solution(%v, %v) = %v, want invalid_interval", round, slots, reserved, got)
			}
			continue
		}
		if err != nil {
			t.Fatalf("round %d: solution(%v, %v) returned %v", round, slots, reserved, err)
		}
		want := referenceAvailable(slots, reserved)
		if !sameIDs(got, want) {
			t.Fatalf("round %d: solution(%v, %v) = %v, want %v", round, slots, reserved, got, want)
		}
	}
}

func TestReservationCalendarThreeHundredThousandOpenSlots(t *testing.T) {
	const slotCount = 300000
	slots := make([]Slot, 0, slotCount)
	for index := slotCount - 1; index >= 0; index-- {
		start := index % 1440
		slots = append(slots, Slot{fmt.Sprintf("S%06d", index), start, start + 1})
	}
	starts := make([]int, 0, len(slots))
	for _, slot := range slots {
		starts = append(starts, slot.Start)
	}
	if sort.IntsAreSorted(starts) {
		t.Fatal("the large case must start in scrambled start order")
	}
	type result struct {
		ids []string
		err error
	}
	completed := make(chan result, 1)
	go func() {
		got, err := solution(Request{Slots: slots})
		completed <- result{got, err}
	}()
	timer := time.NewTimer(4 * time.Second)
	defer timer.Stop()
	var got []string
	select {
	case outcome := <-completed:
		got = outcome.ids
		if outcome.err != nil {
			t.Fatalf("solution with %d open slots returned %v", slotCount, outcome.err)
		}
	case <-timer.C:
		t.Fatalf("solution with %d open slots exceeded 4s", slotCount)
	}
	want := referenceAvailable(slots, nil)
	if !sameIDs(got, want) {
		t.Fatal("solution with 100000 slots does not match the reference")
	}
}
