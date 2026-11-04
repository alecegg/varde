"use strict";

var DEFAULT_LIMIT = 3;
var COUNT = 0;

function makeCounter(start) {
  var value = start === undefined ? 0 : start;
  return function next() {
    value += 1;
    COUNT += 1;
    return value;
  };
}

function total(values, limit) {
  var running = 0;
  var index = 0;
  while (index < values.length && index < limit) {
    running += values[index];
    index += 1;
  }
  return running;
}

var formatter = {
  label: "value",
  render: function (value) {
    return this.label + "=" + String(value);
  },
};

module.exports = { makeCounter: makeCounter, total: total, formatter: formatter };
