using static Harness;

static string Dates(List<Order> orders) => string.Join(",", orders.Select(o => o.Date));

Case("first order on the start date", () =>
{
    var system = new OrderSystem();
    int plan = system.AddRecurring("ann", 1000, 2, "2024-01-15");
    var orders = system.OrdersThrough("2024-01-15");
    Equal(1, orders.Count);
    Equal(new Order(plan, "2024-01-15", 2000), orders[0]);
});

Case("repeats monthly", () =>
{
    var system = new OrderSystem();
    system.AddRecurring("ann", 500, 1, "2024-01-15");
    Equal("2024-01-15,2024-02-15,2024-03-15", Dates(system.OrdersThrough("2024-03-20")));
});

Case("day is clamped to the month length", () =>
{
    var system = new OrderSystem();
    system.AddRecurring("ann", 500, 1, "2024-01-31");
    Equal("2024-01-31,2024-02-29,2024-03-31", Dates(system.OrdersThrough("2024-03-31")));
});

Case("orders are generated once", () =>
{
    var system = new OrderSystem();
    system.AddRecurring("ann", 500, 1, "2024-01-15");
    Equal("2024-01-15", Dates(system.OrdersThrough("2024-01-31")));
    Equal("2024-02-15", Dates(system.OrdersThrough("2024-02-20")));
    Equal("", Dates(system.OrdersThrough("2024-02-20")));
});

Case("cancel stops future orders", () =>
{
    var system = new OrderSystem();
    int plan = system.AddRecurring("ann", 500, 1, "2024-01-15");
    Equal(1, system.OrdersThrough("2024-01-20").Count);
    system.Cancel(plan);
    Equal(0, system.OrdersThrough("2024-06-01").Count);
});

Case("start after the date generates nothing", () =>
{
    var system = new OrderSystem();
    system.AddRecurring("ann", 500, 1, "2024-05-01");
    Equal(0, system.OrdersThrough("2024-04-30").Count);
});

Case("invalid plan is rejected", () =>
{
    var system = new OrderSystem();
    Throws(() => system.AddRecurring("ann", 500, 0, "2024-01-01"));
    Throws(() => system.AddRecurring("ann", -1, 1, "2024-01-01"));
});

Case("orders sorted by date then plan", () =>
{
    var system = new OrderSystem();
    system.AddRecurring("a", 100, 1, "2024-01-20");
    system.AddRecurring("b", 100, 1, "2024-01-10");
    system.AddRecurring("c", 100, 1, "2024-01-10");
    Equal("2,3,1", string.Join(",", system.OrdersThrough("2024-01-31").Select(o => o.RecurringId)));
});

return Finish();
