# report-pipeline behaviour spec

`render_report(csv_text, key_column, value_column)` parses CSV with a header row, sums the numeric value column per key and returns a text report with no trailing newline. Lines: one `<key>: <count> rows, <total>` line per key, formatted `total <t>` with two decimals, sorted by total descending then key ascending, then `TOTAL: <rows> rows, total <t>`. With no data rows the report is exactly `No data`.

1. `region,amount` rows north 10, south 5.5, north 2.25 give `north: 2 rows, total 12.25`, `south: 1 rows, total 5.50`, `TOTAL: 3 rows, total 17.75`.
2. Keys sort by total descending; equal totals sort by key.
3. A quoted field may contain a comma (`"Smith, Jo",4`) and the key is `Smith, Jo`.
4. Blank lines are ignored.
5. A missing key or value column is an error.
6. A non-numeric value is an error.
7. Other columns are ignored and column order does not matter.
8. A header with no data rows renders `No data`.
