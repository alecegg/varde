using System.Globalization;
using System.Text;

public sealed record OrderItem(
    string Sku,
    int Quantity,
    decimal UnitPrice,
    decimal LineTotal);

public sealed record OrderResult(
    IReadOnlyList<OrderItem> Items,
    decimal Subtotal,
    decimal Discount,
    decimal Tax,
    decimal Shipping,
    decimal Total);

public static class Original
{
    public static OrderResult Process(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
        {
            throw new ArgumentException("Input is empty", nameof(input));
        }

        var ls = new List<OrderItem>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        decimal s = 0m;
        var aa = input.Split('\n');
        foreach (var raw in aa)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                continue;
            }

            var p = raw.Split('|');
            if (p.Length != 3)
            {
                throw new ArgumentException("Each row needs three fields", nameof(input));
            }

            var k = p[0].Trim();
            var qx = p[1].Trim();
            var vx = p[2].Trim();
            if (k.Length == 0)
            {
                throw new ArgumentException("SKU is required", nameof(input));
            }

            if (!seen.Add(k))
            {
                throw new ArgumentException("SKUs must be unique", nameof(input));
            }

            int q;
            decimal v;
            if (!int.TryParse(qx, NumberStyles.Integer, CultureInfo.InvariantCulture, out q))
            {
                throw new ArgumentException("Quantity is invalid", nameof(input));
            }

            if (!decimal.TryParse(vx, NumberStyles.Number, CultureInfo.InvariantCulture, out v))
            {
                throw new ArgumentException("Price is invalid", nameof(input));
            }

            if (q < 1 || q > 100 || v < 0m || v > 10000m)
            {
                throw new ArgumentException("Value is outside the allowed range", nameof(input));
            }

            var lt = R(v * q);
            ls.Add(new OrderItem(k, q, R(v), lt));
            s += lt;
        }

        if (ls.Count == 0)
        {
            throw new ArgumentException("No order rows were found", nameof(input));
        }

        s = R(s);
        decimal d = 0m;
        if (s >= 100m) d = R(s * .10m);
        else if (s >= 50m) d = R(s * .05m);
        var n = R(s - d);
        decimal t;
        if (n > 0m)
        {
            t = R(n * .0825m);
        }
        else
        {
            t = 0m;
        }

        decimal h = 0m;
        if (n < 25m)
        {
            if (n >= 0m)
            {
                if (n < 10m)
                {
                    h = 8.95m;
                }
                else
                {
                    h = 8.95m;
                }
            }
        }
        else
        {
            if (n < 75m)
            {
                if (n >= 25m)
                {
                    h = 5.95m;
                }
                else
                {
                    h = 8.95m;
                }
            }
            else
            {
                if (n >= 75m)
                {
                    h = 0m;
                }
                else
                {
                    h = 5.95m;
                }
            }
        }
        var total = R(
            n
            + t
            + h);
        return new OrderResult(ls.AsReadOnly(), s, d, t, h, total);
    }

    public static string Report(OrderResult order)
    {
        if (order is null)
        {
            throw new ArgumentNullException(nameof(order));
        }

        var b = new StringBuilder();
        b.AppendLine("Order");
        b.Append("Items: ")
            .Append(order.Items.Count)
            .AppendLine();
        b.Append("Subtotal: $")
            .Append(F(order.Subtotal))
            .AppendLine();
        b.Append("Discount: $")
            .Append(F(order.Discount))
            .AppendLine();
        b.Append("Tax: $")
            .Append(F(order.Tax))
            .AppendLine();
        b.Append("Shipping: $")
            .Append(F(order.Shipping))
            .AppendLine();
        b.Append("Total: $")
            .Append(F(order.Total));
        return b.ToString().TrimEnd('\r', '\n');
    }

    private static decimal R(decimal x)
    {
        return Math.Round(
            x,
            2,
            MidpointRounding.AwayFromZero);
    }

    private static string F(decimal x)
    {
        return x.ToString(
            "0.00",
            CultureInfo.InvariantCulture);
    }
}
