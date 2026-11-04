const NO_SIZE = 0;
const NO_REMAINDER = 0;

export function wrapIndex(index: number, size: number): number {
  return usable(size) ? folded(remainder(index, size), size) : NO_SIZE;
}

function usable(size: number): boolean {
  return size > NO_SIZE;
}

function remainder(index: number, size: number): number {
  return index % size;
}

function folded(value: number, size: number): number {
  return belowZero(value) ? lifted(value, size) : value;
}

function belowZero(value: number): boolean {
  return value < NO_REMAINDER;
}

function lifted(value: number, size: number): number {
  return value + size;
}
