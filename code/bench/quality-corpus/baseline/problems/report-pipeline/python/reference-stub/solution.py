import csv
import io


def render_report(csv_text, key_column, value_column):
    rows = [
        row for row in csv.reader(io.StringIO(csv_text)) if any(c.strip() for c in row)
    ]
    header, data = rows[0], rows[1:]
    if key_column not in header or value_column not in header:
        raise ValueError("missing column")
    key_at, value_at = header.index(key_column), header.index(value_column)
    groups = {}
    for row in data:
        count, total = groups.get(row[key_at], (0, 0.0))
        groups[row[key_at]] = (count + 1, total + float(row[value_at]))
    if not groups:
        return "No data"
    ordered = sorted(groups.items(), key=lambda item: (-item[1][1], item[0]))
    lines = [
        f"{key}: {count} rows, total {total:.2f}" for key, (count, total) in ordered
    ]
    lines.append(
        f"TOTAL: {len(data)} rows, total {sum(t for _, t in groups.values()):.2f}"
    )
    return "\n".join(lines)
