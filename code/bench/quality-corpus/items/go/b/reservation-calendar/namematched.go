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
	if intervalsRejected(request) {
		return nil, errInvalidInterval
	}
	return slotIdentifiers(slotsInOrder(openSlots(request)), noIdentifiers), nil
}

func intervalsRejected(request Request) bool {
	return declaredSlotsBroken(request) || declaredReservationsBroken(request)
}

func declaredSlotsBroken(request Request) bool {
	return slices.ContainsFunc(request.Slots, offendingSlot)
}

func offendingSlot(slot Slot) bool {
	return !minuteWithinDay(slot.Start) || !minuteWithinDay(slot.End) || slot.Start >= slot.End
}

func minuteWithinDay(minute int) bool {
	return minute >= 0 && minute <= dayEnd
}

func declaredReservationsBroken(request Request) bool {
	return slices.ContainsFunc(request.Reserved, offendingReservation)
}

func offendingReservation(reservation Reservation) bool {
	start := reservation.Start
	end := reservation.End
	return !minuteWithinDay(start) || !minuteWithinDay(end) || start >= end
}

func openSlots(request Request) []Slot {
	return slices.DeleteFunc(slices.Clone(request.Slots), func(slot Slot) bool {
		return !unobstructedSlot(slot, request.Reserved)
	})
}

func unobstructedSlot(slot Slot, reserved []Reservation) bool {
	return !anyConflict(slot, reserved)
}

func anyConflict(slot Slot, reserved []Reservation) bool {
	return slices.ContainsFunc(reserved, func(other Reservation) bool {
		return conflictsWith(slot, other)
	})
}

func conflictsWith(slot Slot, reservation Reservation) bool {
	startsBefore := slot.Start < reservation.End
	endsAfter := reservation.Start < slot.End
	return startsBefore && endsAfter
}

func slotsInOrder(slots []Slot) []Slot {
	slices.SortFunc(slots, slotOrder)
	return slots
}

func slotOrder(left, right Slot) int {
	if left.Start != right.Start {
		return left.Start - right.Start
	}
	return nameOrder(left.ID, right.ID)
}

func nameOrder(left, right string) int {
	return strings.Compare(left, right)
}

func slotIdentifiers(slots []Slot, ids []string) []string {
	for _, slot := range slots {
		ids = append(ids, slot.ID)
	}
	return ids
}
