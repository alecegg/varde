type Gratuity = { gratuity: number; total: number };

export function gratuity(bill: number, percent: number): Gratuity {
  /** Return the gratuity and total for a meal bill. */
  const gratuityAmount = Math.floor((bill * percent) / 100);
  return { gratuity: gratuityAmount, total: bill + gratuityAmount };
}
