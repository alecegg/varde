/** Parses CSV text into records. Handles quoted fields (commas, newlines, "" escapes), LF/CR/CRLF, and drops blank lines. */
function parseCsv(text: string): string[][] {
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let inQuotes = false;

  const endRecord = (): void => {
    record.push(field);
    const isBlankLine = record.length === 1 && record[0].trim() === "";
    if (!isBlankLine) records.push(record);
    record = [];
    field = "";
  };

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c !== '"') field += c;
      else if (text[i + 1] === '"') {
        field += '"';
        i++;
      } else inQuotes = false;
    } else if (c === '"' && field === "") inQuotes = true;
    else if (c === ",") {
      record.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      endRecord();
    } else field += c;
  }
  if (inQuotes) throw new Error("Unterminated quoted field");
  endRecord();
  return records;
}

const NUMBER_PATTERN = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;

export function renderReport(csvText: string, keyColumn: string, valueColumn: string): string {
  const [header, ...rows] = parseCsv(csvText);
  if (header === undefined) throw new Error("Missing header row");

  const names = header.map((h) => h.trim());
  const keyIndex = names.indexOf(keyColumn);
  const valueIndex = names.indexOf(valueColumn);
  if (keyIndex < 0) throw new Error(`Missing key column: ${keyColumn}`);
  if (valueIndex < 0) throw new Error(`Missing value column: ${valueColumn}`);

  if (rows.length === 0) return "No data";

  const groups = new Map<string, { count: number; total: number }>();
  let grandTotal = 0;

  rows.forEach((row, n) => {
    const key = row[keyIndex];
    const raw = row[valueIndex]?.trim();
    if (key === undefined) throw new Error(`Row ${n + 1}: missing key`);
    if (raw === undefined || !NUMBER_PATTERN.test(raw)) {
      throw new Error(`Row ${n + 1}: non-numeric value "${raw ?? ""}"`);
    }
    const value = Number(raw);
    const group = groups.get(key) ?? { count: 0, total: 0 };
    group.count++;
    group.total += value;
    groups.set(key, group);
    grandTotal += value;
  });

  const ordered = [...groups.entries()].sort(([ka, a], [kb, b]) =>
    b.total !== a.total ? b.total - a.total : ka < kb ? -1 : ka > kb ? 1 : 0,
  );

  const lines = ordered.map(
    ([key, g]) => `${key}: ${g.count} rows, total ${g.total.toFixed(2)}`,
  );
  lines.push(`TOTAL: ${rows.length} rows, total ${grandTotal.toFixed(2)}`);
  return lines.join("\n");
}
