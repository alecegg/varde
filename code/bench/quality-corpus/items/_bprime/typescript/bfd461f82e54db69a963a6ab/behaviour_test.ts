import { wrapIndex } from "./solution.ts";

function check(expected: number, actual: number): void {
  if (expected !== actual) {
    throw new Error(`expected ${expected} but got ${actual}`);
  }
}

check(2, wrapIndex(7, 5));
check(4, wrapIndex(-1, 5));
check(0, wrapIndex(0, 5));
check(0, wrapIndex(5, 5));
check(2, wrapIndex(-7, 3));
check(0, wrapIndex(12, 4));
check(3, wrapIndex(3, 8));
check(0, wrapIndex(-8, 8));
check(0, wrapIndex(1, 1));
check(6, wrapIndex(-2, 8));
check(0, wrapIndex(7, 0));
check(0, wrapIndex(-3, 0));
