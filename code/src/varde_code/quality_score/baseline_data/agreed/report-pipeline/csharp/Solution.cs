using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

public static class Report
{
    // Parses CSV, sums valueColumn per keyColumn and renders the text report.
    // Throws on a missing column or a non-numeric value.
    public static string Render(string csvText, string keyColumn, string valueColumn)
    {
        var records = ParseRecords(csvText ?? "");
        if (records.Count == 0)
            throw new ArgumentException("CSV has no header row");

        var header = records[0];
        int keyIndex = IndexOfColumn(header, keyColumn);
        int valueIndex = IndexOfColumn(header, valueColumn);
        int needed = Math.Max(keyIndex, valueIndex);

        var groups = new Dictionary<string, (int Count, decimal Total)>(StringComparer.Ordinal);
        int rows = 0;
        decimal grand = 0m;

        for (int i = 1; i < records.Count; i++)
        {
            var record = records[i];
            if (record.Count <= needed)
                throw new FormatException($"Row {i} has too few fields");

            if (!decimal.TryParse(record[valueIndex], NumberStyles.Number,
                    CultureInfo.InvariantCulture, out var value))
                throw new FormatException($"Row {i}: non-numeric value '{record[valueIndex]}'");

            var key = record[keyIndex];
            groups.TryGetValue(key, out var current);
            groups[key] = (current.Count + 1, current.Total + value);
            rows++;
            grand += value;
        }

        if (rows == 0)
            return "No data";

        var lines = groups
            .OrderByDescending(g => g.Value.Total)
            .ThenBy(g => g.Key, StringComparer.Ordinal)
            .Select(g => $"{g.Key}: {g.Value.Count} rows, total {Money(g.Value.Total)}")
            .ToList();
        lines.Add($"TOTAL: {rows} rows, total {Money(grand)}");
        return string.Join("\n", lines);
    }

    private static string Money(decimal value) =>
        value.ToString("F2", CultureInfo.InvariantCulture);

    private static int IndexOfColumn(List<string> header, string name)
    {
        int index = header.FindIndex(h => h.Trim() == name);
        if (index < 0)
            throw new ArgumentException($"Missing column '{name}'");
        return index;
    }

    // Splits CSV text into records. Handles quoted fields (embedded commas,
    // newlines and "" escapes) and drops blank lines, so callers see only
    // meaningful records.
    private static List<List<string>> ParseRecords(string text)
    {
        var records = new List<List<string>>();
        var row = new List<string>();
        var field = new StringBuilder();
        bool inQuotes = false;
        bool quoted = false; // current field used quotes, so it is not a blank line

        void EndField()
        {
            row.Add(field.ToString());
            field.Clear();
        }

        void EndRecord()
        {
            EndField();
            bool blank = row.Count == 1 && !quoted && row[0].Trim().Length == 0;
            if (!blank)
                records.Add(row);
            row = new List<string>();
            quoted = false;
        }

        for (int i = 0; i < text.Length; i++)
        {
            char c = text[i];
            if (inQuotes)
            {
                if (c == '"')
                {
                    if (i + 1 < text.Length && text[i + 1] == '"')
                    {
                        field.Append('"');
                        i++;
                    }
                    else
                    {
                        inQuotes = false;
                    }
                }
                else
                {
                    field.Append(c);
                }
            }
            else if (c == '"')
            {
                inQuotes = true;
                quoted = true;
            }
            else if (c == ',')
            {
                EndField();
                quoted = true; // a comma means the line is not blank
            }
            else if (c == '\r' || c == '\n')
            {
                if (c == '\r' && i + 1 < text.Length && text[i + 1] == '\n')
                    i++;
                EndRecord();
            }
            else
            {
                field.Append(c);
            }
        }

        if (inQuotes)
            throw new FormatException("Unterminated quoted field");

        if (field.Length > 0 || row.Count > 0 || quoted)
            EndRecord();

        return records;
    }
}
