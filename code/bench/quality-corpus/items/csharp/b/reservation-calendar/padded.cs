public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking) =>
        OutcomeFor(
            SlotsInvalid(booking.Slots),
            SpansInvalid(booking.Reserved),
            BookingIdsOf(booking));

    private static Verdict OutcomeFor(bool slotsInvalid, bool spansInvalid, string[] ids)
    {
        bool broken = slotsInvalid || spansInvalid;
        if (broken)
        {
            string reason = "invalid_interval";
            return new Verdict(null, reason);
        }
        return new Verdict(ids, null);
    }

    private static bool SlotsInvalid(Slot[] slots)
    {
        foreach (Slot slot in slots)
        {
            bool ok = IntervalValid(slot.Start, slot.End);
            if (!ok)
            {
                return true;
            }
        }
        return false;
    }

    private static bool SpansInvalid(Span[] spans)
    {
        foreach (Span span in spans)
        {
            bool ok = IntervalValid(span.Start, span.End);
            if (!ok)
            {
                return true;
            }
        }
        return false;
    }

    private static bool IntervalValid(int start, int end)
    {
        bool forward = start < end;
        bool aboveZero = start >= 0;
        bool withinDay = end <= 1440;
        bool valid = forward && aboveZero && withinDay;
        return valid;
    }

    private static string[] BookingIdsOf(Booking booking)
    {
        Slot[] slots = booking.Slots;
        Span[] spans = booking.Reserved;
        Slot[] free = FreeSlotsOf(slots, spans);
        Slot[] ordered = OrderedSlotsOf(free);
        string[] ids = ExtractedIdsOf(ordered);
        return ids;
    }

    private static Slot[] FreeSlotsOf(Slot[] slots, Span[] spans)
    {
        var free = new System.Collections.Generic.List<Slot>();
        foreach (Slot slot in slots)
        {
            bool remains = SlotFreeOf(slot, spans);
            if (remains)
            {
                free.Add(slot);
            }
        }
        return free.ToArray();
    }

    private static bool SlotFreeOf(Slot slot, Span[] spans)
    {
        foreach (Span span in spans)
        {
            bool taken = IntervalsOverlap(slot, span);
            if (taken)
            {
                return false;
            }
        }
        return true;
    }

    private static bool IntervalsOverlap(Slot slot, Span span)
    {
        bool startsBefore = slot.Start < span.End;
        bool endsAfter = span.Start < slot.End;
        bool overlaps = startsBefore && endsAfter;
        return overlaps;
    }

    private static Slot[] OrderedSlotsOf(Slot[] slots)
    {
        System.Linq.IOrderedEnumerable<Slot> byStart = StartOrderFor(slots);
        System.Linq.IOrderedEnumerable<Slot> sequence =
            System.Linq.Enumerable.ThenBy(byStart, slot => slot.Id, Ordinal);
        return System.Linq.Enumerable.ToArray(sequence);
    }

    private static System.Linq.IOrderedEnumerable<Slot> StartOrderFor(Slot[] slots)
    {
        System.Linq.IOrderedEnumerable<Slot> sequence =
            System.Linq.Enumerable.OrderBy(slots, slot => slot.Start);
        return sequence;
    }

    private static string[] ExtractedIdsOf(Slot[] slots)
    {
        string[] ids = new string[slots.Length];
        for (int index = 0; index < slots.Length; index++)
        {
            ids[index] = slots[index].Id;
        }
        return ids;
    }
}
