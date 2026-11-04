using System;
using System.Collections.Generic;

static Solution.Slot Slot(string id, int start, int end) => new Solution.Slot(id, start, end);

static Solution.Span Span(int start, int end) => new Solution.Span(start, end);

static void ExpectIds(Solution.Verdict verdict, string[] want, string label)
{
    if (verdict.Error != null)
    {
        throw new InvalidOperationException($"{label} returned {verdict.Error}");
    }
    if (verdict.Ids.Length != want.Length)
    {
        throw new InvalidOperationException($"{label} has {verdict.Ids.Length} ids");
    }
    for (int index = 0; index < want.Length; index++)
    {
        if (verdict.Ids[index] != want[index])
        {
            string got = verdict.Ids[index];
            throw new InvalidOperationException($"{label}[{index}] = {got}, want {want[index]}");
        }
    }
}

static void ExpectBroken(Solution.Verdict verdict, string label)
{
    if (verdict.Error != "invalid_interval")
    {
        throw new InvalidOperationException($"{label} returned {verdict.Error}");
    }
}

var cases = new (Solution.Booking Booking, string[] Want)[]
{
    (new Solution.Booking(new Solution.Slot[0], new Solution.Span[0]), new string[0]),
    (new Solution.Booking(new[] { Slot("A", 540, 600) }, new Solution.Span[0]), new[] { "A" }),
    (
        new Solution.Booking(new[] { Slot("A", 540, 600) }, new[] { Span(540, 600) }),
        new string[0]),
    (
        new Solution.Booking(
            new[] { Slot("A", 480, 540), Slot("B", 540, 600) },
            new[] { Span(540, 570) }),
        new[] { "A" }),
    (
        new Solution.Booking(new[] { Slot("A", 540, 600) }, new[] { Span(570, 630) }),
        new string[0]),
    (
        new Solution.Booking(
            new[] { Slot("B", 600, 660), Slot("A", 540, 600) },
            new[] { Span(700, 720) }),
        new[] { "A", "B" }),
    (
        new Solution.Booking(
            new[] { Slot("B", 540, 600), Slot("A", 540, 600) },
            new Solution.Span[0]),
        new[] { "A", "B" }),
    (
        new Solution.Booking(
            new[] { Slot("A", 0, 30), Slot("B", 1410, 1440) },
            new[] { Span(30, 60) }),
        new[] { "A", "B" }),
    (
        new Solution.Booking(
            new[]
            {
                Slot("a", 600, 630), Slot("é", 600, 630), Slot("_", 600, 630),
                Slot("A", 600, 630), Slot("2", 600, 630), Slot("e", 600, 630),
            },
            new Solution.Span[0]),
        new[] { "2", "A", "_", "a", "e", "é" }),
    (
        new Solution.Booking(new[] { Slot("day-end", 1439, 1440) },
            new[] { Span(1439, 1440) }),
        new string[0]),
};

foreach (var row in cases)
{
    ExpectIds(Solution.solution(row.Booking), row.Want, "case");
}

var broken = new (Solution.Booking Booking, string Label)[]
{
    (
        new Solution.Booking(new[] { Slot("A", 600, 600) }, new Solution.Span[0]),
        "empty slot"),
    (
        new Solution.Booking(new[] { Slot("A", 540, 600) }, new[] { Span(800, 800) }),
        "empty span"),
    (
        new Solution.Booking(new[] { Slot("A", 700, 600) }, new Solution.Span[0]),
        "reversed slot"),
    (
        new Solution.Booking(new[] { Slot("A", 540, 1500) }, new Solution.Span[0]),
        "slot past midnight"),
    (
        new Solution.Booking(new[] { Slot("A", 1400, 1441) }, new Solution.Span[0]),
        "slot past day boundary"),
    (
        new Solution.Booking(new[] { Slot("A", 1400, int.MinValue) }, new Solution.Span[0]),
        "slot end underflow"),
    (
        new Solution.Booking(new Solution.Slot[0], new[] { Span(1, int.MinValue) }),
        "span end underflow"),
    (
        new Solution.Booking(new Solution.Slot[0], new[] { Span(-30, 60) }),
        "span before midnight"),
};

foreach (var row in broken)
{
    ExpectBroken(Solution.solution(row.Booking), row.Label);
}

string[] names = new string[] { "A", "B", "C", "D", "E", "F", "G", "H" };
Random random = new Random(515151);
for (int iteration = 0; iteration < 1200; iteration++)
{
    int slotCount = random.Next(0, 9);
    int spanCount = random.Next(0, 5);
    Solution.Slot[] slots = new Solution.Slot[slotCount];
    Solution.Span[] spans = new Solution.Span[spanCount];
    for (int index = 0; index < slotCount; index++)
    {
        int start = random.Next(0, 1400);
        int end = start + random.Next(1, 40);
        slots[index] = Slot(names[index], start, end);
    }
    for (int index = 0; index < spanCount; index++)
    {
        int start = random.Next(0, 1400);
        int end = start + random.Next(1, 40);
        spans[index] = Span(start, end);
    }
    var expected = new List<(int Start, string Id)>();
    foreach (Solution.Slot slot in slots)
    {
        bool taken = false;
        foreach (Solution.Span span in spans)
        {
            if (slot.Start < span.End && span.Start < slot.End)
            {
                taken = true;
            }
        }
        if (!taken)
        {
            expected.Add((slot.Start, slot.Id));
        }
    }
    expected.Sort((left, right) =>
        left.Start != right.Start
            ? left.Start.CompareTo(right.Start)
            : string.CompareOrdinal(left.Id, right.Id));
    string[] want = new string[expected.Count];
    for (int index = 0; index < expected.Count; index++)
    {
        want[index] = expected[index].Id;
    }
    Solution.Verdict verdict = Solution.solution(new Solution.Booking(slots, spans));
    ExpectIds(verdict, want, "random");
}

List<Solution.Slot> manySlots = new List<Solution.Slot>();
List<Solution.Span> manySpans = new List<Solution.Span>();
List<(int Start, string Id)> expectedLarge = new List<(int, string)>();
for (int index = 0; index < 1000; index++)
{
    int start = index * 1 % 1400;
    string name = names[index % names.Length] + index.ToString("D4");
    manySlots.Add(Slot(name, start, start + 2));
}
for (int index = 0; index < 200; index++)
{
    int start = index * 7 % 1400;
    manySpans.Add(Span(start, start + 3));
}
foreach (Solution.Slot slot in manySlots)
{
    bool taken = false;
    foreach (Solution.Span span in manySpans)
    {
        if (slot.Start < span.End && span.Start < slot.End)
        {
            taken = true;
        }
    }
    if (!taken)
    {
        expectedLarge.Add((slot.Start, slot.Id));
    }
}
expectedLarge.Sort((left, right) =>
    left.Start != right.Start
        ? left.Start.CompareTo(right.Start)
        : string.CompareOrdinal(left.Id, right.Id));
Solution.Verdict large = Solution.solution(
    new Solution.Booking(manySlots.ToArray(), manySpans.ToArray()));
if (large.Error != null)
{
    throw new InvalidOperationException($"large input returned {large.Error}");
}
if (large.Ids.Length != expectedLarge.Count)
{
    throw new InvalidOperationException("large input id count mismatch");
}
for (int index = 0; index < large.Ids.Length; index++)
{
    if (large.Ids[index] != expectedLarge[index].Id)
    {
        throw new InvalidOperationException($"large input id mismatch at {index}");
    }
}
