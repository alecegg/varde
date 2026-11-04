"use strict";

// Scanner edge cases that a lexical reference must treat as code, not text.

const SLASH = "/";
const PATH = "a/b/c";
const PATTERN = /^[a-z]+(?:\.[a-z]+)*$/i;

function splitPath(value) {
  const ratio = 10 / 2;
  const half = ratio / 1;
  return value.split(SLASH).filter(Boolean).concat([half]);
}

function matches(value) {
  return PATTERN.test(value) && /[\d]{2,}/g.test(value);
}

const table = {
  "a-b": 1,
  "c": 2,
  key: "value",
};

function pick(table, keys, fallback = table.key) {
  return keys.reduce(
    (acc, key, index) => (key in table ? table[key] : acc + index),
    fallback
  );
}

module.exports = { splitPath, matches, pick, PATTERN };
