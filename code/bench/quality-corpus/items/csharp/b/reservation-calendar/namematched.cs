public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking) =>
        VerdictFrom(SlotsUnusable(booking.Slots), SpansUnusable(booking.Reserved),
            IdsForBooking(booking));

    private static Verdict VerdictFrom(bool slotsUnusable, bool spansUnusable, string[] ids) =>
        slotsUnusable || spansUnusable
            ? new Verdict(null, "invalid_interval") : new Verdict(ids, null);

    private static bool SlotsUnusable(Slot[] slots) =>
        System.Linq.Enumerable.Any(slots, slot => !IntervalAcceptable(slot.Start, slot.End));

    private static bool SpansUnusable(Span[] spans) =>
        System.Linq.Enumerable.Any(spans, span => !IntervalAcceptable(span.Start, span.End));

    private static bool IntervalAcceptable(int start, int end) =>
        start >= 0 && start < end && end <= 1440;

    private static string[] IdsForBooking(Booking booking) =>
        IdentityIds(OrderedByStart(RemainingSlots(booking.Slots, booking.Reserved)));

    private static Slot[] RemainingSlots(Slot[] slots, Span[] spans) =>
        System.Array.FindAll(slots, slot => SlotRemainsFree(slot, spans));

    private static bool SlotRemainsFree(Slot slot, Span[] spans) =>
        !System.Linq.Enumerable.Any(spans, span => IntervalsTouchOverlap(slot, span));

    private static bool IntervalsTouchOverlap(Slot slot, Span span) =>
        slot.Start < span.End && span.Start < slot.End;

    private static System.Linq.IOrderedEnumerable<Slot> OrderedByStart(Slot[] slots) =>
        System.Linq.Enumerable.ThenBy(SlotsInStartOrder(slots), slot => slot.Id, Ordinal);

    private static System.Linq.IOrderedEnumerable<Slot> SlotsInStartOrder(Slot[] slots) =>
        System.Linq.Enumerable.OrderBy(slots, slot => slot.Start);

    private static string[] IdentityIds(System.Linq.IOrderedEnumerable<Slot> slots) =>
        System.Array.ConvertAll(System.Linq.Enumerable.ToArray(slots), slot => slot.Id);
}
