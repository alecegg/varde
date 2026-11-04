import assert from "node:assert/strict";
import { remaining } from "./solution.ts";

assert.equal(remaining(100, [10, 20]), 70);
assert.equal(remaining(50, []), 50);
assert.equal(remaining(20, [5, 5, 2]), 8);
