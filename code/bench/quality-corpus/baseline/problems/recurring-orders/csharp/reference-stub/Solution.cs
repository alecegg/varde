public record Order(int RecurringId, string Date, int TotalCents);

public class OrderSystem
{
    class Plan
    {
        public int Id, Year, Month, Day, TotalCents, Generated;
        public bool Active = true;
    }

    readonly List<Plan> plans = new();

    public int AddRecurring(string customer, int unitCents, int quantity, string start)
    {
        if (quantity < 1 || unitCents < 0) throw new ArgumentException("invalid order");
        var parts = start.Split('-').Select(int.Parse).ToArray();
        var plan = new Plan { Id = plans.Count + 1, Year = parts[0], Month = parts[1], Day = parts[2], TotalCents = unitCents * quantity };
        plans.Add(plan);
        return plan.Id;
    }

    public void Cancel(int id) => plans[id - 1].Active = false;

    public List<Order> OrdersThrough(string through)
    {
        var orders = new List<Order>();
        foreach (var plan in plans)
        {
            while (plan.Active)
            {
                var date = DateOf(plan);
                if (string.CompareOrdinal(date, through) > 0) break;
                orders.Add(new Order(plan.Id, date, plan.TotalCents));
                plan.Generated++;
            }
        }
        return orders.OrderBy(o => o.Date, StringComparer.Ordinal).ThenBy(o => o.RecurringId).ToList();
    }

    static string DateOf(Plan plan)
    {
        int index = plan.Year * 12 + plan.Month - 1 + plan.Generated;
        int year = index / 12, month = index % 12 + 1;
        int day = Math.Min(plan.Day, DateTime.DaysInMonth(year, month));
        return $"{year:D4}-{month:D2}-{day:D2}";
    }
}
