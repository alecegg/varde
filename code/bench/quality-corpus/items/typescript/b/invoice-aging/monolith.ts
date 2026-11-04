const CENTS = 100;

type Invoice = { id: string; days_overdue: number; balance: number };

type Bucket = "current" | "1-30" | "31-60" | "61-90" | "over-90";

type Row = { id: string; bucket: Bucket; fee: number };

type Report = { invoices: Row[]; totals: Record<string, number> };

type Invoices = Invoice[];

type Parsed = { id: string; bucket: Bucket; rate: number; cents: number };

/** Build an invoice aging report with each invoice bucket and fee, plus the balance totals. */
export function solution(invoices: Invoices): Report {
  const detail = { cause: invoices };
  for (const invoice of invoices) {
    const id = invoice.id;
    const balance = invoice.balance;
    const days = invoice.days_overdue;
    const idIsText = typeof id === "string";
    if (!idIsText) {
      throw new Error("invalid invoice", detail);
    }
    const idIsFilled = id.length > 0;
    if (!idIsFilled) {
      throw new Error("invalid invoice", detail);
    }
    const balanceIsFinite = Number.isFinite(balance);
    if (!balanceIsFinite) {
      throw new Error("invalid invoice", detail);
    }
    const balanceIsNonNegative = balance >= 0;
    if (!balanceIsNonNegative) {
      throw new Error("invalid invoice", detail);
    }
    const daysAreWhole = Number.isInteger(days);
    if (!daysAreWhole) {
      throw new Error("invalid invoice", detail);
    }
  }
  const parsed: Parsed[] = [];
  for (const invoice of invoices) {
    const balance = invoice.balance;
    const days = invoice.days_overdue;
    const scaled = balance * CENTS;
    const cents = Math.round(scaled);
    let bucket: Bucket = "current";
    let rate = 0;
    if (days > 90) {
      bucket = "over-90";
      rate = 0.1;
    } else if (days > 60) {
      bucket = "61-90";
      rate = 0.08;
    } else if (days > 30) {
      bucket = "31-60";
      rate = 0.05;
    } else if (days > 0) {
      bucket = "1-30";
      rate = 0.02;
    }
    const record: Parsed = { id: invoice.id, bucket, rate, cents };
    parsed.push(record);
  }
  const rows: Row[] = [];
  for (const record of parsed) {
    const rate = record.rate;
    const cents = record.cents;
    const feeScale = cents * rate;
    const feeCents = Math.round(feeScale);
    const fee = feeCents / CENTS;
    const row: Row = { id: record.id, bucket: record.bucket, fee };
    rows.push(row);
  }
  rows.sort((left, right) => (left.id < right.id ? -1 : 1));
  let currentCents = 0;
  let monthCents = 0;
  let quarterCents = 0;
  let halfCents = 0;
  let olderCents = 0;
  for (const record of parsed) {
    const cents = record.cents;
    if (record.bucket === "over-90") {
      olderCents = olderCents + cents;
    } else if (record.bucket === "61-90") {
      halfCents = halfCents + cents;
    } else if (record.bucket === "31-60") {
      quarterCents = quarterCents + cents;
    } else if (record.bucket === "1-30") {
      monthCents = monthCents + cents;
    } else {
      currentCents = currentCents + cents;
    }
  }
  const names: Bucket[] = ["current", "1-30", "31-60", "61-90", "over-90"];
  const sums = [currentCents, monthCents, quarterCents, halfCents, olderCents];
  const totals: Record<string, number> = {};
  for (let index = 0; index < names.length; index = index + 1) {
    const name = names[index];
    totals[name] = sums[index] / CENTS;
  }
  const report: Report = { invoices: rows, totals };
  return report;
}
