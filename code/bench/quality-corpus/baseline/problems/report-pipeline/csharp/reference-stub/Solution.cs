using System.Globalization;

public static class Report
{
    static List<string> ParseLine(string line)
    {
        var fields = new List<string>();
        var field = new System.Text.StringBuilder();
        bool quoted = false;
        foreach (char ch in line)
        {
            if (ch == '"') quoted = !quoted;
            else if (ch == ',' && !quoted) { fields.Add(field.ToString()); field.Clear(); }
            else field.Append(ch);
        }
        fields.Add(field.ToString());
        return fields;
    }

    public static string Render(string csvText, string keyColumn, string valueColumn)
    {
        var rows = csvText.Split('\n').Where(l => l.Trim() != "").Select(ParseLine).ToList();
        var header = rows[0];
        int keyAt = header.IndexOf(keyColumn), valueAt = header.IndexOf(valueColumn);
        if (keyAt < 0 || valueAt < 0) throw new ArgumentException("missing column");
        var data = rows.Skip(1).ToList();
        var groups = new Dictionary<string, (int Count, double Total)>();
        foreach (var row in data)
        {
            double value = double.Parse(row[valueAt], CultureInfo.InvariantCulture);
            var (count, total) = groups.GetValueOrDefault(row[keyAt]);
            groups[row[keyAt]] = (count + 1, total + value);
        }
        if (groups.Count == 0) return "No data";
        var ordered = groups.OrderByDescending(g => g.Value.Total).ThenBy(g => g.Key, StringComparer.Ordinal).ToList();
        var lines = ordered.Select(g => $"{g.Key}: {g.Value.Count} rows, total {Money(g.Value.Total)}").ToList();
        lines.Add($"TOTAL: {data.Count} rows, total {Money(ordered.Sum(g => g.Value.Total))}");
        return string.Join("\n", lines);
    }

    static string Money(double value) => value.ToString("F2", CultureInfo.InvariantCulture);
}
