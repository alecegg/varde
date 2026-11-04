import assert from "node:assert/strict";
import { fahrenheit } from "./solution.ts";

assert.equal(fahrenheit(0), 32);
assert.equal(fahrenheit(100), 212);
assert.equal(fahrenheit(-40), -40);
