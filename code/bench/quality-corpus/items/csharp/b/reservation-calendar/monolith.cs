public static class Solution
{
    public record Slot(string Id, int Start, int End);

    public record Span(int Start, int End);

    public record Booking(Slot[] Slots, Span[] Reserved);

    public record Verdict(string[] Ids, string Error);

    /// <summary>Report the slots still free after applying every reservation.</summary>
    public static Verdict solution(Booking booking)
    {
        for (int index = 0; index < booking.Slots.Length; index++)
        {
            Slot slot = booking.Slots[index];
            if (slot.Start < 0)
            {
                return new Verdict(null, "invalid_interval");
            }
            else
            {
                if (slot.End > 1440)
                {
                    return new Verdict(null, "invalid_interval");
                }
                else
                {
                    if (slot.Start >= slot.End)
                    {
                        return new Verdict(null, "invalid_interval");
                    }
                }
            }
        }

        for (int index = 0; index < booking.Reserved.Length; index++)
        {
            Span span = booking.Reserved[index];
            if (span.Start < 0)
            {
                return new Verdict(null, "invalid_interval");
            }
            else
            {
                if (span.End > 1440)
                {
                    return new Verdict(null, "invalid_interval");
                }
                else
                {
                    if (span.Start >= span.End)
                    {
                        return new Verdict(null, "invalid_interval");
                    }
                }
            }
        }

        var free = new System.Collections.Generic.List<Slot>();
        for (int index = 0; index < booking.Slots.Length; index++)
        {
            Slot slot = booking.Slots[index];
            bool taken = false;
            for (int other = 0; other < booking.Reserved.Length; other++)
            {
                Span span = booking.Reserved[other];
                bool startsInside = slot.Start < span.End;
                bool endsInside = span.Start < slot.End;
                if (startsInside && endsInside)
                {
                    taken = true;
                }
            }
            if (!taken)
            {
                free.Add(slot);
            }
        }

        for (int first = 1; first < free.Count; first++)
        {
            Slot held = free[first];
            int position = first - 1;
            bool keepGoing = position >= 0;
            while (keepGoing)
            {
                Slot other = free[position];
                bool after = other.Start > held.Start;
                if (other.Start == held.Start)
                {
                    after = System.String.CompareOrdinal(other.Id, held.Id) > 0;
                }
                if (!after)
                {
                    keepGoing = false;
                }
                else
                {
                    free[position + 1] = other;
                    position = position - 1;
                    keepGoing = position >= 0;
                }
            }
            free[position + 1] = held;
        }

        string[] ids = new string[free.Count];
        for (int index = 0; index < free.Count; index++)
        {
            ids[index] = free[index].Id;
        }
        return new Verdict(ids, null);
    }
}
