export function remaining(start: number, expenses: number[]): number {
  /** Return the amount left after expenses. */
  const spent = expenses.reduce((total, expense) => total + expense, 0);
  return start - spent;
}
