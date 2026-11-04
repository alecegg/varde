import assert from "node:assert/strict";
import { test } from "node:test";
import { renderReport } from "./solution.ts";

test("aggregates by key", () => {
  const text = "region,amount\nnorth,10\nsouth,5.5\nnorth,2.25\n";
  assert.equal(
    renderReport(text, "region", "amount"),
    "north: 2 rows, total 12.25\nsouth: 1 rows, total 5.50\nTOTAL: 3 rows, total 17.75",
  );
});

test("sorts by total then key", () => {
  const lines = renderReport("k,v\nb,5\na,5\nc,7\n", "k", "v").split("\n");
  assert.deepEqual(lines.slice(0, 3).map((l) => l.split(":")[0]), ["c", "a", "b"]);
});

test("quoted field with comma", () => {
  assert.ok(renderReport('name,v\n"Smith, Jo",4\n', "name", "v").startsWith("Smith, Jo: 1 rows, total 4.00"));
});

test("blank lines are ignored", () => {
  assert.equal(
    renderReport("k,v\n\na,1\n\n\na,2\n\n", "k", "v"),
    "a: 2 rows, total 3.00\nTOTAL: 2 rows, total 3.00",
  );
});

test("missing column is an error", () => {
  assert.throws(() => renderReport("k,v\na,1\n", "k", "amount"));
  assert.throws(() => renderReport("k,v\na,1\n", "name", "v"));
});

test("non-numeric value is an error", () => {
  assert.throws(() => renderReport("k,v\na,abc\n", "k", "v"));
});

test("other columns and order are ignored", () => {
  assert.equal(
    renderReport("id,amount,team\n1,3,x\n2,4,x\n", "team", "amount"),
    "x: 2 rows, total 7.00\nTOTAL: 2 rows, total 7.00",
  );
});

test("header only has no data", () => {
  assert.equal(renderReport("k,v\n", "k", "v"), "No data");
});
