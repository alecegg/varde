type Gratuity = { gratuity: number; total: number };

function g(a: number, b: number): number {
  return Math.floor((a * b) / 100);
}

export function gratuity(bill: number, percent: number): Gratuity {
  /** Return the gratuity and total for a meal bill. */
  const x = g(bill, percent);
  const y = bill + x;
  return { gratuity: x, total: y };
}
