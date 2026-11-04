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
	for _, slot := range request.Slots {
		if slot.Start < 0 {
			return nil, errInvalidInterval
		}
		if slot.End > dayEnd {
			return nil, errInvalidInterval
		}
		if slot.Start >= slot.End {
			return nil, errInvalidInterval
		}
	}
	for _, reservation := range request.Reserved {
		if reservation.Start < 0 {
			return nil, errInvalidInterval
		}
		if reservation.End > dayEnd {
			return nil, errInvalidInterval
		}
		if reservation.Start >= reservation.End {
			return nil, errInvalidInterval
		}
	}
	slotCount := len(request.Slots)
	covered := make([]bool, slotCount)
	for index, slot := range request.Slots {
		slotStart := slot.Start
		slotEnd := slot.End
		for _, reservation := range request.Reserved {
			startsBeforeEnd := slotStart < reservation.End
			endsAfterStart := reservation.Start < slotEnd
			if startsBeforeEnd && endsAfterStart {
				covered[index] = true
			}
		}
	}
	open := make([]Slot, 0, slotCount)
	for index, slot := range request.Slots {
		if covered[index] {
			continue
		}
		open = append(open, slot)
	}
	sort.Slice(open, func(left, right int) bool {
		leftSlot := open[left]
		rightSlot := open[right]
		if leftSlot.Start != rightSlot.Start {
			return leftSlot.Start < rightSlot.Start
		}
		return leftSlot.ID < rightSlot.ID
	})
	ids := make([]string, 0, len(open))
	for _, slot := range open {
		identifier := slot.ID
		ids = append(ids, identifier)
	}
	return ids, nil
}
