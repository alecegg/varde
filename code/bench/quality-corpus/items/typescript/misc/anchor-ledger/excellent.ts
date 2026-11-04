function integerAmount(value: number): number {
  if (!Number.isInteger(value)) {
    throw new TypeError("ledger values must be integers");
  }
  return value;
}

export function balance(opening: number, entries: number[]): number {
  /** Return the account balance after applying signed ledger entries. */
  return integerAmount(opening) + entries.reduce((sum, entry) => sum + integerAmount(entry), 0);
}
