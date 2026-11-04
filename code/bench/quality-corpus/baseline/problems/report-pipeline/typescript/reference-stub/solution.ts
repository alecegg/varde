function parseLine(line: string): string[] {
  const fields: string[] = [];
  let field = "";
  let quoted = false;
  for (const ch of line) {
    if (ch === '"') quoted = !quoted;
    else if (ch === "," && !quoted) {
      fields.push(field);
      field = "";
    } else field += ch;
  }
  fields.push(field);
  return fields;
}

export function renderReport(csvText: string, keyColumn: string, valueColumn: string): string {
  const rows = csvText.split("\n").filter((line) => line.trim() !== "").map(parseLine);
  const [header, ...data] = rows;
  const keyAt = header.indexOf(keyColumn);
  const valueAt = header.indexOf(valueColumn);
  if (keyAt < 0 || valueAt < 0) throw new Error("missing column");
  const groups = new Map<string, { count: number; total: number }>();
  for (const row of data) {
    const value = Number(row[valueAt]);
    if (row[valueAt] === undefined || row[valueAt].trim() === "" || Number.isNaN(value)) throw new Error("bad value");
    const group = groups.get(row[keyAt]) ?? { count: 0, total: 0 };
    groups.set(row[keyAt], { count: group.count + 1, total: group.total + value });
  }
  if (groups.size === 0) return "No data";
  const ordered = [...groups].sort((a, b) => b[1].total - a[1].total || (a[0] < b[0] ? -1 : 1));
  const lines = ordered.map(([key, g]) => `${key}: ${g.count} rows, total ${g.total.toFixed(2)}`);
  const grand = ordered.reduce((sum, [, g]) => sum + g.total, 0);
  lines.push(`TOTAL: ${data.length} rows, total ${grand.toFixed(2)}`);
  return lines.join("\n");
}
