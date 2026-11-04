export interface Account {
  owner: string;
  balance: number;
}

export type Status = "open" | "closed";

export const MAX_RETRIES = 3;
export const DEFAULT_NAME = "anonymous";

export function total(accounts: Account[]): number {
  let running = 0;
  for (const account of accounts) {
    running += account.balance;
  }
  return running;
}

export function summarize(accounts: Account[]): Record<string, number> {
  const ranked = [...accounts].sort((a, b) => b.balance - a.balance);
  return Object.fromEntries(
    ranked.slice(0, MAX_RETRIES).map((a) => [a.owner, a.balance]),
  );
}
