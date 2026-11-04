import assert from "node:assert/strict";
import { gratuity } from "./solution.ts";

assert.deepStrictEqual(gratuity(20, 10), { gratuity: 2, total: 22 });
assert.deepStrictEqual(gratuity(45, 20), { gratuity: 9, total: 54 });
assert.deepStrictEqual(gratuity(0, 15), { gratuity: 0, total: 0 });
