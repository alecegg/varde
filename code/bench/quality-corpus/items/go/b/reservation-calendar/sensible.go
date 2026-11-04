package corpus

import (
	"errors"
	"sort"
)

var errInvalidInterval = errors.New("invalid_interval")

const dayEnd = 1440

type Slot struct {
	ID    string
	Start int
	End   int
}

type Reservation struct {
	Start int
	End   int
}

type Request struct {
	Slots    []Slot
	Reserved []Reservation
}

// solution returns the identifiers of slots that no reservation overlaps.
func solution(request Request) ([]string, error) {
	if !validIntervals(request) {
		return nil, errInvalidInterval
	}
	open := available(request)
	sortSlots(open)
	return idsOf(open), nil
}

func validIntervals(request Request) bool {
	for _, slot := range request.Slots {
		if slot.Start < 0 || slot.End > dayEnd || slot.Start >= slot.End {
			return false
		}
	}
	for _, reservation := range request.Reserved {
		if reservation.Start < 0 || reservation.End > dayEnd {
			return false
		}
		if reservation.Start >= reservation.End {
			return false
		}
	}
	return true
}

func available(request Request) []Slot {
	open := make([]Slot, 0, len(request.Slots))
	for _, slot := range request.Slots {
		taken := false
		for _, reservation := range request.Reserved {
			if slot.Start < reservation.End && reservation.Start < slot.End {
				taken = true
			}
		}
		if !taken {
			open = append(open, slot)
		}
	}
	return open
}

func sortSlots(slots []Slot) {
	sort.Slice(slots, func(left, right int) bool {
		if slots[left].Start != slots[right].Start {
			return slots[left].Start < slots[right].Start
		}
		return slots[left].ID < slots[right].ID
	})
}

func idsOf(slots []Slot) []string {
	ids := make([]string, 0, len(slots))
	for _, slot := range slots {
		ids = append(ids, slot.ID)
	}
	return ids
}
