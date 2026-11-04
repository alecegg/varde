using System.Globalization;

public static class Original
{
    public static string CreateReceipt(string line)
    {
        if (line == null) throw new FormatException("Input is required.");
        var raw = Q(line);
        if (raw.Length == 0) throw new FormatException("Input is required.");
        var pieces = raw.Split(',');
        if (pieces.Length != 3) throw new FormatException("Expected three fields.");
        var cls = L(Q(pieces[0]));
        var htxt = Q(pieces[1]);
        var vtxt = L(Q(pieces[2]));
        int hh;
        if (!P(htxt, out hh)) throw new FormatException("Hours must be an integer.");
        if (hh < 1 || hh > 168) throw new FormatException("Hours are outside the allowed range.");
        bool vv;
        if (vtxt == "true") vv = true;
        else if (vtxt == "false") vv = false;
        else throw new FormatException("Validation must be true or false.");
        decimal rate;
        if (cls == "car") rate = 5m;
        else if (cls == "motorcycle") rate = 3m;
        else if (cls == "van") rate = 8m;
        else throw new FormatException("Unknown vehicle class.");

        decimal bill = 0m;
        int left = hh;
        while (left > 0)
        {
            int day = left > 24 ? 24 : left;
            decimal piece = 0m;
            for (int i = 1; i <= day; i++)
            {
                if (i <= 2) piece += rate;
                else if (i <= 5) piece += rate * 1.5m;
                else piece += rate * 2m;
            }
            decimal cap = rate * 24m;
            if (piece > cap) piece = cap;
            bill += piece;
            left -= day;
        }
        if (vv) bill = bill * 0.90m;
        bill = bill + bill * 0.08m;
        bill = Math.Round(bill, 2, MidpointRounding.AwayFromZero);
        var amount = F(bill);
        var validation = V(vv);
        return "Vehicle: " + cls + "\nHours: " + hh.ToString(CultureInfo.InvariantCulture) + "\nValidated: " + validation + "\nTotal: $" + amount;
    }

    private static string Q(string s)
    {
        return s.Trim();
    }

    private static string L(string s)
    {
        return s.ToLowerInvariant();
    }

    private static bool P(string s, out int value)
    {
        return int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
    }

    private static string F(decimal value)
    {
        return value.ToString("F2", CultureInfo.InvariantCulture);
    }

    private static string V(bool value)
    {
        if (value) return "true";
        return "false";
    }

    public static string CreateReport(IEnumerable<string> lines)
    {
        if (lines == null) throw new ArgumentNullException(nameof(lines));
        var result = new List<string>();
        foreach (var line in lines)
        {
            if (line == null || line.Trim().Length == 0) continue;
            result.Add(CreateReceipt(line));
        }
        return string.Join("\n", result);
    }

    public static decimal CalculateFee(string vehicleClass, int hours, bool validated)
    {
        if (hours < 1 || hours > 168) throw new ArgumentOutOfRangeException(nameof(hours));
        var cls = vehicleClass == null ? "" : vehicleClass.Trim().ToLowerInvariant();
        decimal rate;
        if (cls == "car") rate = 5m;
        else if (cls == "motorcycle") rate = 3m;
        else if (cls == "van") rate = 8m;
        else throw new ArgumentException("Unknown vehicle class.", nameof(vehicleClass));
        var result = 0m;
        var remaining = hours;
        while (remaining > 0)
        {
            var block = Math.Min(24, remaining);
            decimal blockTotal = 0m;
            if (block <= 2)
            {
                blockTotal = block * rate;
            }
            else
            {
                if (block > 5)
                {
                    blockTotal = 2m * rate + 3m * rate * 1.5m + (block - 5) * rate * 2m;
                }
                else
                {
                    blockTotal = 2m * rate + (block - 2) * rate * 1.5m;
                }
            }
            if (blockTotal > rate * 24m) blockTotal = rate * 24m;
            result += blockTotal;
            remaining -= block;
        }
        if (validated) result *= 0.9m;
        result *= 1.08m;
        return Math.Round(result, 2, MidpointRounding.AwayFromZero);
    }
}
