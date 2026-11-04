export interface Order {
  recurringId: number;
  date: string;
  totalCents: number;
}

interface Plan {
  id: number;
  customer: string;
  totalCents: number;
  startYear: number;
  startMonth: number; // 0-based
  startDay: number;
  generated: number; // occurrences already returned; also the index of the next one
  cancelled: boolean;
}

const MAX_YEAR = 9999;

const pad = (n: number, width: number) => String(n).padStart(width, "0");

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

/** Pure arithmetic (no Date), so years 0000-0099 are not remapped to 1900-1999. */
function daysInMonth(year: number, month: number): number {
  if (month === 1) return isLeapYear(year) ? 29 : 28;
  return month === 3 || month === 5 || month === 8 || month === 10 ? 30 : 31;
}

/** Parses a strict YYYY-MM-DD string, rejecting impossible dates such as 2024-02-30. */
function parseDate(text: string): { year: number; month: number; day: number } {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    if (month >= 0 && month < 12 && day >= 1 && day <= daysInMonth(year, month)) {
      return { year, month, day };
    }
  }
  throw new Error(`Invalid date: ${text}`);
}

/**
 * Date of the nth occurrence (0 = start), or undefined once past year 9999.
 * Always derived from the original start day, so a clamp in a short month
 * (Jan 31 -> Feb 29) does not drift later months (-> Mar 31).
 */
function occurrenceDate(plan: Plan, n: number): string | undefined {
  const monthIndex = plan.startMonth + n;
  const year = plan.startYear + Math.floor(monthIndex / 12);
  if (year > MAX_YEAR) return undefined;
  const month = monthIndex % 12;
  const day = Math.min(plan.startDay, daysInMonth(year, month));
  return `${pad(year, 4)}-${pad(month + 1, 2)}-${pad(day, 2)}`;
}

export class OrderSystem {
  private plans: Plan[] = [];

  addRecurring(customer: string, unitCents: number, quantity: number, start: string): number {
    if (!Number.isSafeInteger(quantity) || quantity < 1) {
      throw new Error("quantity must be an integer >= 1");
    }
    if (!Number.isSafeInteger(unitCents) || unitCents < 0) {
      throw new Error("unitCents must be an integer >= 0");
    }
    const totalCents = unitCents * quantity;
    if (!Number.isSafeInteger(totalCents)) {
      throw new Error("order total exceeds the safe integer range");
    }
    const { year, month, day } = parseDate(start);
    const id = this.plans.length + 1;
    this.plans.push({
      id,
      customer,
      totalCents,
      startYear: year,
      startMonth: month,
      startDay: day,
      generated: 0,
      cancelled: false,
    });
    return id;
  }

  cancel(id: number): void {
    const plan = this.plans[id - 1];
    if (plan) plan.cancelled = true;
  }

  /** Returns each due order exactly once; ISO dates compare correctly as strings. */
  ordersThrough(through: string): Order[] {
    parseDate(through);
    const due: Order[] = [];
    for (const plan of this.plans) {
      if (plan.cancelled) continue;
      for (;;) {
        const date = occurrenceDate(plan, plan.generated);
        if (date === undefined || date > through) break;
        due.push({ recurringId: plan.id, date, totalCents: plan.totalCents });
        plan.generated++;
      }
    }
    return due.sort((a, b) =>
      a.date < b.date ? -1 : a.date > b.date ? 1 : a.recurringId - b.recurringId,
    );
  }
}
