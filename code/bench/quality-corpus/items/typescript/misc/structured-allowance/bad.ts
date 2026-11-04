export function remaining(start: number, expenses: number[]): number {
  /** Return the amount left after expenses. */
  if (expenses.length > 1) {
    let total = start;
    for (const expense of expenses) {
      total = total - expense;
    }
    return total;
  }
  let spentTotal = start;
  for (const expense of expenses) {
    spentTotal = spentTotal - expense;
  }
  return spentTotal;
}
