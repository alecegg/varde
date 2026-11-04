export interface Order {
  recurringId: number;
  date: string;
  totalCents: number;
}

interface Plan {
  id: number;
  year: number;
  month: number;
  day: number;
  totalCents: number;
  generated: number;
  active: boolean;
}

const pad = (n: number): string => String(n).padStart(2, "0");

export class OrderSystem {
  private plans: Plan[] = [];

  addRecurring(customer: string, unitCents: number, quantity: number, start: string): number {
    if (quantity < 1 || unitCents < 0) throw new Error("invalid order");
    const [year, month, day] = start.split("-").map(Number);
    const id = this.plans.length + 1;
    this.plans.push({ id, year, month, day, totalCents: unitCents * quantity, generated: 0, active: true });
    return id;
  }

  cancel(id: number): void {
    this.plans[id - 1].active = false;
  }

  ordersThrough(through: string): Order[] {
    const orders: Order[] = [];
    for (const plan of this.plans) {
      while (plan.active) {
        const date = this.dateOf(plan);
        if (date > through) break;
        orders.push({ recurringId: plan.id, date, totalCents: plan.totalCents });
        plan.generated++;
      }
    }
    return orders.sort((a, b) => (a.date === b.date ? a.recurringId - b.recurringId : a.date < b.date ? -1 : 1));
  }

  private dateOf(plan: Plan): string {
    const index = plan.year * 12 + plan.month - 1 + plan.generated;
    const year = Math.floor(index / 12);
    const month = (index % 12) + 1;
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return `${year}-${pad(month)}-${pad(Math.min(plan.day, lastDay))}`;
  }
}
