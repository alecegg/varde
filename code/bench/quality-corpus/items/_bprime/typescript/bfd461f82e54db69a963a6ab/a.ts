export function wrapIndex(index: number, size: number): number {
  if (size <= 0) {
    return 0;
  }
  const remainder = index % size;
  if (remainder < 0) {
    return remainder + size;
  }
  return remainder;
}
