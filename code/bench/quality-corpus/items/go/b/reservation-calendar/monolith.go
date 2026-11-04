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
	slotCount := len(request.Slots)
	reservationCount := len(request.Reserved)
	for index := 0; index < slotCount; index++ {
		slot := request.Slots[index]
		startsBeforeDay := slot.Start < 0
		endsAfterDay := slot.End > dayEnd
		emptyInterval := slot.Start >= slot.End
		if startsBeforeDay || endsAfterDay || emptyInterval {
			return nil, errInvalidInterval
		}
	}
	for index := 0; index < reservationCount; index++ {
		reservation := request.Reserved[index]
		startsBeforeDay := reservation.Start < 0
		endsAfterDay := reservation.End > dayEnd
		emptyInterval := reservation.Start >= reservation.End
		if startsBeforeDay || endsAfterDay || emptyInterval {
			return nil, errInvalidInterval
		}
	}
	covered := make([]bool, slotCount)
	for index := 0; index < slotCount; index++ {
		slot := request.Slots[index]
		slotStart := slot.Start
		slotEnd := slot.End
		blocked := false
		for reservationIndex := 0; reservationIndex < reservationCount; reservationIndex++ {
			reservation := request.Reserved[reservationIndex]
			startsBeforeEnd := slotStart < reservation.End
			endsAfterStart := reservation.Start < slotEnd
			overlaps := startsBeforeEnd && endsAfterStart
			if overlaps {
				blocked = true
			}
		}
		covered[index] = blocked
	}
	openIndexes := make([]int, 0, slotCount)
	for index := 0; index < slotCount; index++ {
		isCovered := covered[index]
		if isCovered {
			continue
		}
		openIndexes = append(openIndexes, index)
	}
	openCount := len(openIndexes)
	sort.Slice(openIndexes, func(left int, right int) bool {
		leftSlot := request.Slots[openIndexes[left]]
		rightSlot := request.Slots[openIndexes[right]]
		leftStart := leftSlot.Start
		rightStart := rightSlot.Start
		startsDiffer := leftStart != rightStart
		if startsDiffer {
			leftStartsEarlier := leftStart < rightStart
			return leftStartsEarlier
		}
		leftIdentifier := leftSlot.ID
		rightIdentifier := rightSlot.ID
		leftNamedEarlier := leftIdentifier < rightIdentifier
		return leftNamedEarlier
	})
	ids := make([]string, 0, openCount)
	for index := 0; index < openCount; index++ {
		slotIndex := openIndexes[index]
		slot := request.Slots[slotIndex]
		identifier := slot.ID
		ids = append(ids, identifier)
	}
	return ids, nil
}
