public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking)
    {
        foreach (Slot slot in booking.Slots)
        {
            bool forward = slot.Start < slot.End;
            bool inRange = slot.Start >= 0 && slot.End <= 1440;
            if (!forward || !inRange)
            {
                return new Verdict(null, "invalid_interval");
            }
        }
        foreach (Span span in booking.Reserved)
        {
            bool forward = span.Start < span.End;
            bool inRange = span.Start >= 0 && span.End <= 1440;
            if (!forward || !inRange)
            {
                return new Verdict(null, "invalid_interval");
            }
        }
        var free = new System.Collections.Generic.List<Slot>();
        foreach (Slot slot in booking.Slots)
        {
            bool taken = false;
            foreach (Span span in booking.Reserved)
            {
                bool startsBefore = slot.Start < span.End;
                bool endsAfter = span.Start < slot.End;
                if (startsBefore && endsAfter)
                {
                    taken = true;
                }
            }
            bool available = !taken;
            if (available)
            {
                free.Add(slot);
            }
        }
        free.Sort((left, right) =>
        {
            int byStart = left.Start.CompareTo(right.Start);
            return byStart != 0 ? byStart : System.String.CompareOrdinal(left.Id, right.Id);
        });
        string[] ids = new string[free.Count];
        for (int index = 0; index < free.Count; index++)
        {
            ids[index] = free[index].Id;
        }
        return new Verdict(ids, null);
    }
}
