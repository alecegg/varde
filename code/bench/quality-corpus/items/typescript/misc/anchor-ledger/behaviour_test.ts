import assert from "node:assert/strict";
import { balance } from "./solution.ts";

assert.equal(balance(10, [5, -3]), 12);
assert.equal(balance(0, []), 0);
assert.equal(balance(100, [-20, -30]), 50);
