using static Harness;

var calls = new List<string>();
var failing = new HashSet<string>();

bool Send(string channel, string message)
{
    calls.Add($"{channel}:{message}");
    return !failing.Contains(channel);
}

Dispatcher Make(int emailLimit, int smsLimit = 9)
{
    calls.Clear();
    failing.Clear();
    return new Dispatcher(new() { ("email", emailLimit), ("sms", smsLimit) }, Send);
}

string Run(Dispatcher d, params int[] times) => string.Join(",", times.Select(t => d.Dispatch("m", t) ?? "none"));

Case("first channel is used", () =>
{
    var d = Make(5);
    Equal("email", d.Dispatch("hi", 0));
    Equal("email:hi", string.Join(",", calls));
});

Case("limit falls back", () => Equal("email,email,sms", Run(Make(2), 0, 1, 2)));

Case("window expires", () => Equal("email,sms,email", Run(Make(1), 0, 30, 61)));

Case("failed send falls back", () =>
{
    var d = Make(5);
    failing.Add("email");
    Equal("sms", d.Dispatch("m", 0));
});

Case("failed send keeps quota", () =>
{
    var d = Make(1);
    failing.Add("email");
    Equal("sms", d.Dispatch("m", 0));
    failing.Clear();
    Equal("email", d.Dispatch("m", 1));
});

Case("all unavailable returns null", () =>
{
    var d = Make(5, 5);
    failing.Add("email");
    failing.Add("sms");
    Equal<string?>(null, d.Dispatch("m", 0));
    Equal("email:m,sms:m", string.Join(",", calls));
});

Case("boundary at the window edge", () => Equal("email,sms,email", Run(Make(1), 0, 59, 60)));

Case("limited channel is not attempted", () =>
{
    var d = Make(1);
    d.Dispatch("a", 0);
    d.Dispatch("b", 1);
    Equal("email:a,sms:b", string.Join(",", calls));
});

return Finish();
