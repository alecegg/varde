function noArgs() {
  return 0;
}

function one(a) {
  return a;
}

function two(a, b) {
  return a + b;
}

function defaults(a, b = 1) {
  return a + b;
}

function rest(a, ...values) {
  return a + values.length;
}

const arrow = (a, b, c) => a + b + c;
const arrowOne = (a) => a;

function destructured({ a, b }) {
  return a + b;
}

function arrayPattern([first, second]) {
  return first + second;
}

function nested() {
  function inner(x, y) {
    return x + y;
  }
  return inner(1, 2);
}

function annotatedish(a, b) {
  return a * b;
}

function four(a, b, c, d) {
  return a + b + c + d;
}
