public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    private static readonly System.StringComparer Ordinal = System.StringComparer.Ordinal;

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking)
    {
        if (!SlotsOk(booking.Slots) || !SpansOk(booking.Reserved))
        {
            return new Verdict(null, "invalid_interval");
        }
        return new Verdict(IdsOf(FreeSlots(booking)), null);
    }

    private static bool SlotsOk(Slot[] slots)
    {
        foreach (Slot slot in slots)
        {
            if (slot.Start >= slot.End || slot.Start < 0 || slot.End > 1440)
            {
                return false;
            }
        }
        return true;
    }

    private static bool SpansOk(Span[] spans)
    {
        foreach (Span span in spans)
        {
            if (span.Start >= span.End || span.Start < 0 || span.End > 1440)
            {
                return false;
            }
        }
        return true;
    }

    private static Slot[] FreeSlots(Booking booking)
    {
        var free = new System.Collections.Generic.List<Slot>();
        foreach (Slot slot in booking.Slots)
        {
            bool taken = System.Linq.Enumerable.Any(
                booking.Reserved, span => slot.Start < span.End && span.Start < slot.End);
            if (!taken)
            {
                free.Add(slot);
            }
        }
        return free.ToArray();
    }

    private static string[] IdsOf(Slot[] slots) =>
        System.Array.ConvertAll(
            System.Linq.Enumerable.ToArray(System.Linq.Enumerable.ThenBy(
                System.Linq.Enumerable.OrderBy(slots, slot => slot.Start),
                slot => slot.Id,
                Ordinal)),
            slot => slot.Id);
}
