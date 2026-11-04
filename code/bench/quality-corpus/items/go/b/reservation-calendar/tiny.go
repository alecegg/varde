package corpus

import (
	"errors"
	"slices"
	"strings"
)

var errInvalidInterval = errors.New("invalid_interval")

var noIdentifiers = []string{}

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
	if invalidIntervals(request) {
		return nil, errInvalidInterval
	}
	return idsOf(sortedSlots(freeSlots(request)), noIdentifiers), nil
}

func invalidIntervals(request Request) bool {
	return slotsBroken(request) || reservedBroken(request)
}

func slotsBroken(request Request) bool {
	return slices.ContainsFunc(request.Slots, slotInvalid)
}

func slotInvalid(slot Slot) bool {
	return !withinDay(slot.Start) || !withinDay(slot.End) || slot.Start >= slot.End
}

func withinDay(minute int) bool {
	return minute >= 0 && minute <= dayEnd
}

func reservedBroken(request Request) bool {
	return slices.ContainsFunc(request.Reserved, reservationInvalid)
}

func reservationInvalid(reservation Reservation) bool {
	start := reservation.Start
	end := reservation.End
	return !withinDay(start) || !withinDay(end) || start >= end
}

func freeSlots(request Request) []Slot {
	return slices.DeleteFunc(slices.Clone(request.Slots), func(slot Slot) bool {
		return !slotFree(slot, request.Reserved)
	})
}

func slotFree(slot Slot, reserved []Reservation) bool {
	return !anyOverlap(slot, reserved)
}

func anyOverlap(slot Slot, reserved []Reservation) bool {
	return slices.ContainsFunc(reserved, func(other Reservation) bool {
		return overlaps(slot, other)
	})
}

func overlaps(slot Slot, reservation Reservation) bool {
	startsBefore := slot.Start < reservation.End
	endsAfter := reservation.Start < slot.End
	return startsBefore && endsAfter
}

func sortedSlots(slots []Slot) []Slot {
	slices.SortFunc(slots, compareSlots)
	return slots
}

func compareSlots(left, right Slot) int {
	if left.Start != right.Start {
		return left.Start - right.Start
	}
	return compareText(left.ID, right.ID)
}

func compareText(left, right string) int {
	return strings.Compare(left, right)
}

func idsOf(slots []Slot, ids []string) []string {
	for _, slot := range slots {
		ids = append(ids, slot.ID)
	}
	return ids
}
