package corpus

import (
	"errors"
	"slices"
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
	if intervalsRejected(request) {
		return nil, errInvalidInterval
	}
	return identifiersOf(orderedSlots(openSlots(request))), nil
}

func intervalsRejected(request Request) bool {
	badSlots := slotListInvalid(request)
	badReserved := reservationListInvalid(request)
	rejected := badSlots || badReserved
	return rejected
}

func slotListInvalid(request Request) bool {
	slots := request.Slots
	for index := 0; index < len(slots); index++ {
		slot := slots[index]
		if slotBeyondBounds(slot) {
			return true
		}
	}
	return false
}

func slotBeyondBounds(slot Slot) bool {
	badStart := !minuteInDay(slot.Start)
	badEnd := !minuteInDay(slot.End)
	reversed := slot.Start >= slot.End
	return badStart || badEnd || reversed
}

func minuteInDay(minute int) bool {
	belowStart := minute < 0
	beyondEnd := minute > dayEnd
	inside := !belowStart && !beyondEnd
	return inside
}

func reservationListInvalid(request Request) bool {
	reserved := request.Reserved
	for index := 0; index < len(reserved); index++ {
		reservation := reserved[index]
		if reservationBeyondBounds(reservation) {
			return true
		}
	}
	return false
}

func reservationBeyondBounds(reservation Reservation) bool {
	badStart := !minuteInDay(reservation.Start)
	badEnd := !minuteInDay(reservation.End)
	reversed := reservation.Start >= reservation.End
	return badStart || badEnd || reversed
}

func openSlots(request Request) (open []Slot) {
	for _, slot := range request.Slots {
		if vacantSlot(slot, request.Reserved) {
			open = append(open, slot)
		}
	}
	return
}

func vacantSlot(slot Slot, reserved []Reservation) bool {
	conflict := anyConflict(slot, reserved)
	free := !conflict
	return free
}

func anyConflict(slot Slot, reserved []Reservation) bool {
	for index := 0; index < len(reserved); index++ {
		other := reserved[index]
		conflict := collides(slot, other)
		if conflict {
			return true
		}
	}
	return false
}

func collides(slot Slot, reservation Reservation) bool {
	startsBeforeEnd := slot.Start < reservation.End
	endsAfterStart := reservation.Start < slot.End
	collides := startsBeforeEnd && endsAfterStart
	return collides
}

func orderedSlots(slots []Slot) []Slot {
	if len(slots) < 2 {
		return slots
	}
	slices.SortFunc(slots, compareOrder)
	return slots
}

func compareOrder(left, right Slot) int {
	sameStart := left.Start == right.Start
	if !sameStart {
		return left.Start - right.Start
	}
	return compareNames(left.ID, right.ID)
}

func compareNames(left, right string) int {
	for index := 0; index < len(left) && index < len(right); index++ {
		if left[index] != right[index] {
			return int(left[index]) - int(right[index])
		}
	}
	return len(left) - len(right)
}

func identifiersOf(slots []Slot) (ids []string) {
	ids = make([]string, 0, len(slots))
	for index := range slots {
		identifier := slots[index].ID
		ids = append(ids, identifier)
	}
	return
}
