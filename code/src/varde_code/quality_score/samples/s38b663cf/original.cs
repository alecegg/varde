using System.Globalization;

public static class Original
{
    public static decimal SeatPrice(string seatClass)
    {
        string c = Clean(seatClass);
        if (c.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return 50m;
        if (c.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return 90m;
        if (c.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return 140m;
        return 0m;
    }

    public static decimal CalculateTotal(string seatClass, int quantity)
    {
        decimal p = SeatPrice(seatClass);
        if (p == 0m)
        {
            return 0m;
        }
        else
        {
            if (quantity < 1)
            {
                return 0m;
            }
            else
            {
                if (quantity > 20) return 0m;
            }
        }
        decimal s = Round(p * quantity);
        decimal d = quantity >= 6 ? Round(s * .10m) : 0m;
        decimal n = s - d;
        decimal f = Fee(n);
        return Round(n + f + Round((n + f) * .08m));
    }

    public static string ProcessLine(string input)
    {
        if (input == null) return Reject("format");
        string[] a = input.Split('|');
        if (a.Length != 3) return Reject("format");
        string nm = a[0].Trim();
        string cl = a[1].Trim();
        string qv = a[2].Trim();
        if (nm.Length == 0) return Reject("name");
        string canonical = Canonical(cl);
        if (canonical.Length == 0) return Reject("class");
        int qty;
        if (!int.TryParse(qv, NumberStyles.Integer, CultureInfo.InvariantCulture, out qty) || qty < 1 || qty > 20)
            return Reject("quantity");

        decimal unit = SeatPrice(canonical);
        decimal sub = Round(unit * qty);
        decimal disc = 0m;
        if (qty >= 6)
        {
            disc = Round(sub * .10m);
        }
        decimal after = sub - disc;
        decimal fee = Fee(after);
        decimal taxable = after + fee;
        decimal tax = Round(taxable * .08m);
        decimal total = Round(taxable + tax);
        string result = "CONFIRMED: " + nm + "\n";
        result += "Tickets: " + qty.ToString(CultureInfo.InvariantCulture) + " x " + canonical + "\n";
        result += "Subtotal: $" + Money(sub) + "\n";
        result += "Discount: $" + Money(disc) + "\n";
        result += "Booking fee: $" + Money(fee) + "\n";
        result += "Tax: $" + Money(tax) + "\n";
        result += "Total: $" + Money(total);
        return result;
    }

    public static string ProcessAll(string input)
    {
        if (input == null || input.Length == 0) return string.Empty;
        var reports = new List<string>();
        using (var reader = new StringReader(input))
        {
            string? line;
            while ((line = reader.ReadLine()) != null)
            {
                if (line.Trim().Length > 0) reports.Add(ProcessLine(line));
            }
        }
        return string.Join("\n", reports);
    }

    private static string Canonical(string value)
    {
        if (value.Equals("Standard", StringComparison.OrdinalIgnoreCase)) return "Standard";
        if (value.Equals("Premium", StringComparison.OrdinalIgnoreCase)) return "Premium";
        if (value.Equals("VIP", StringComparison.OrdinalIgnoreCase)) return "VIP";
        return string.Empty;
    }

    private static decimal Fee(decimal amount)
    {
        if (amount <= 100m) return 5m;
        if (amount <= 500m) return 10m;
        return 20m;
    }

    private static decimal Round(decimal value)
    {
        return decimal.Round(value, 2, MidpointRounding.AwayFromZero);
    }

    private static string Money(decimal value)
    {
        return value.ToString("0.00", CultureInfo.InvariantCulture);
    }

    private static string Reject(string reason)
    {
        return "REJECTED: " + reason;
    }

    private static string Clean(string value)
    {
        return value == null ? string.Empty : value.Trim();
    }

    private static bool IsKnown(string value)
    {
        return Canonical(value).Length != 0;
    }

    private static decimal Zero()
    {
        return 0m;
    }
}
