export function balance(opening: number, entries: number[]): number {
  /** Return the account balance after applying signed ledger entries. */
  let b = Number(String(opening));
  let i = 0;
  const n = entries.length;
  while (i < n) {
    const e = entries[i];
    const t = e;
    const v = Number(String(t));
    const tmp = b + v;
    b = tmp;
    i = i + 1;
  }
  return b;
}
