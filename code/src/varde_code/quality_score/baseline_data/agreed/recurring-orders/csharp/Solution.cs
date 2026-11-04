using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

public sealed record Order(int RecurringId, string Date, int TotalCents);

public sealed class OrderSystem
{
    private const string IsoFormat = "yyyy-MM-dd";

    // One monthly recurring plan. It owns its schedule, so callers never deal
    // with month arithmetic, clamping, or what has already been generated.
    private sealed class Plan
    {
        public int Id { get; }
        public int TotalCents { get; }
        public bool Cancelled { get; set; }

        private readonly DateOnly _start;
        private int _generated;

        public Plan(int id, int totalCents, DateOnly start)
        {
            Id = id;
            TotalCents = totalCents;
            _start = start;
        }

        // Emits every not-yet-generated order dated on or before `through`.
        // Each date is computed from the original start (not the previous
        // order) so a clamped month, e.g. Feb 29, doesn't drag later months
        // down to the clamped day: 01-31, 02-29, 03-31.
        public IEnumerable<Order> TakeDue(DateOnly through)
        {
            while (!Cancelled)
            {
                var date = _start.AddMonths(_generated);
                if (date > through) yield break;
                _generated++;
                yield return new Order(Id, date.ToString(IsoFormat, CultureInfo.InvariantCulture), TotalCents);
            }
        }
    }

    private readonly List<Plan> _plans = new();

    public int AddRecurring(string customer, int unitCents, int quantity, string start)
    {
        if (unitCents < 0) throw new ArgumentOutOfRangeException(nameof(unitCents), "unitCents must not be negative");
        if (quantity < 1) throw new ArgumentOutOfRangeException(nameof(quantity), "quantity must be at least 1");

        var startDate = ParseDate(start);
        var total = checked(unitCents * quantity);

        var id = _plans.Count + 1;
        _plans.Add(new Plan(id, total, startDate));
        return id;
    }

    // Cancelling an unknown or already-cancelled plan is a no-op, so callers
    // need not track plan state.
    public void Cancel(int id)
    {
        if (id >= 1 && id <= _plans.Count) _plans[id - 1].Cancelled = true;
    }

    public List<Order> OrdersThrough(string through)
    {
        var limit = ParseDate(through);
        return _plans
            .SelectMany(plan => plan.TakeDue(limit))
            .OrderBy(order => order.Date, StringComparer.Ordinal)
            .ThenBy(order => order.RecurringId)
            .ToList();
    }

    private static DateOnly ParseDate(string s) =>
        DateOnly.ParseExact(s, IsoFormat, CultureInfo.InvariantCulture, DateTimeStyles.None);
}
