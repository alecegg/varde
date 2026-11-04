public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking) =>
        VerdictOf(SlotsBad(booking.Slots), SpansBad(booking.Reserved), IdsOf(booking));

    private static Verdict VerdictOf(bool slotsBad, bool spansBad, string[] ids) =>
        slotsBad || spansBad ? new Verdict(null, "invalid_interval") : new Verdict(ids, null);

    private static bool SlotsBad(Slot[] slots) =>
        System.Linq.Enumerable.Any(slots, slot => !IntervalOk(slot.Start, slot.End));

    private static bool SpansBad(Span[] spans) =>
        System.Linq.Enumerable.Any(spans, span => !IntervalOk(span.Start, span.End));

    private static bool IntervalOk(int start, int end) =>
        start < end && start >= 0 && end <= 1440;

    private static string[] IdsOf(Booking booking) =>
        Ids(Ordered(Free(booking.Slots, booking.Reserved)));

    private static Slot[] Free(Slot[] slots, Span[] spans) =>
        System.Array.FindAll(slots, slot => FreeOne(slot, spans));

    private static bool FreeOne(Slot slot, Span[] spans) =>
        !System.Linq.Enumerable.Any(spans, span => Overlaps(slot, span));

    private static bool Overlaps(Slot slot, Span span) =>
        slot.Start < span.End && span.Start < slot.End;

    private static System.Linq.IOrderedEnumerable<Slot> Ordered(Slot[] slots) =>
        System.Linq.Enumerable.ThenBy(Started(slots), slot => slot.Id, Ordinal);

    private static System.Linq.IOrderedEnumerable<Slot> Started(Slot[] slots) =>
        System.Linq.Enumerable.OrderBy(slots, slot => slot.Start);

    private static string[] Ids(System.Linq.IOrderedEnumerable<Slot> slots) =>
        System.Array.ConvertAll(System.Linq.Enumerable.ToArray(slots), slot => slot.Id);
}
