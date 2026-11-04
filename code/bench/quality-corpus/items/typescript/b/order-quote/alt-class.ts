type Item = { sku: string; qty: number; price: string };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Failure = { error: string; index: number | null };
type Line = { sku: string; qty: number; unit_cents: number; line_cents: number };
type Amounts = { subtotal: number; tier_discount: number; coupon_discount: number; net: number };

const REGIONS: Record<string, { tax: number; shipping: number; threshold: number }> = {
  EU: { tax: 2000, shipping: 800, threshold: 10000 },
  US: { tax: 700, shipping: 500, threshold: 7500 },
  ASIA: { tax: 1000, shipping: 1200, threshold: 15000 },
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  if (!request.items.length) return { error: "EMPTY_ORDER", index: null };
  if (request.items.length > 50) return { error: "TOO_MANY_ITEMS", index: null };
  const quote = new Quote();
  const rowIssue = quote.checkRows(request);
  if (rowIssue) return rowIssue;
  quote.setOptions(request);
  const combineIssue = quote.combineRows();
  if (combineIssue) return combineIssue;
  const optionIssue = quote.checkOptions();
  if (optionIssue) return optionIssue;
  return quote.buildQuote();
}

class Quote {
  private rows: { sku: string; qty: number; price: string; cents: number }[] = [];
  private tier = "";
  private coupon = "";
  private region = "";
  private merged = new Map<string, { qty: number; cents: number }>();

  setOptions(request: Request): void {
    this.tier = request.tier.trim().toLowerCase();
    this.coupon = request.coupon.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase());
    this.region = request.region.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase());
  }

  checkRows(request: Request): Failure | null {
    this.rows = request.items.map((item) => ({
      sku: item.sku.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
      qty: item.qty,
      price: item.price,
      cents: 0,
    }));
    for (let index = 0; index < this.rows.length; index++) {
      const issue = this.checkRow(this.rows[index], index);
      if (issue) return issue;
    }
    return null;
  }

  checkRow(row: (typeof this.rows)[number], index: number): Failure | null {
    if (!/^[A-Z0-9-]{3,12}$/.test(row.sku)) return { error: "BAD_SKU", index };
    if (!Number.isInteger(row.qty) || row.qty < 1 || row.qty > 1000) {
      return { error: "BAD_QTY", index };
    }
    const cents = this.priceCents(row.price);
    if (cents === null) return { error: "BAD_PRICE", index };
    row.cents = cents;
    return null;
  }

  priceCents(price: string): number | null {
    if (typeof price !== "string" || !/^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(price)) return null;
    const [whole, fraction = ""] = price.split(".");
    const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
    return cents > 0 ? cents : null;
  }

  combineRows(): Failure | null {
    for (let index = 0; index < this.rows.length; index++) {
      const row = this.rows[index];
      const prior = this.merged.get(row.sku);
      if (prior && prior.cents !== row.cents) return { error: "PRICE_CONFLICT", index };
      const qty = row.qty + (prior?.qty ?? 0);
      if (qty > 1000) return { error: "BAD_QTY", index };
      this.merged.set(row.sku, { qty, cents: row.cents });
    }
    return null;
  }

  checkOptions(): Failure | null {
    if (!(this.tier === "basic" || this.tier === "silver" || this.tier === "gold")) {
      return { error: "BAD_TIER", index: null };
    }
    if (!this.validCoupon()) return { error: "BAD_COUPON", index: null };
    if (!(this.region in REGIONS)) return { error: "BAD_REGION", index: null };
    return null;
  }

  validCoupon(): boolean {
    if (this.coupon === "" || this.coupon === "FREESHIP") return true;
    const match = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(this.coupon);
    return Boolean(match && Number(match[2]) <= (match[1] === "PCT" ? 50 : 500));
  }

  buildQuote() {
    const lines = this.makeLines();
    const amounts = this.calculate(lines);
    const region = REGIONS[this.region];
    const shipping =
      this.coupon === "FREESHIP" || amounts.net >= region.threshold ? 0 : region.shipping;
    const tax = Math.floor((2 * amounts.net * region.tax + 10000) / 20000);
    return this.resultFields(lines, amounts, shipping, tax);
  }

  makeLines(): Line[] {
    return [...this.merged.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([sku, item]) => ({
        sku,
        qty: item.qty,
        unit_cents: item.cents,
        line_cents: item.qty * item.cents,
      }));
  }

  calculate(lines: Line[]): Amounts {
    const subtotal = lines.reduce((sum, line) => sum + line.line_cents, 0);
    const rate = this.tier === "gold" ? 1000 : this.tier === "silver" ? 500 : 0;
    const tier_discount = Math.floor((2 * subtotal * rate + 10000) / 20000);
    const afterTier = subtotal - tier_discount;
    const coupon_discount = this.discount(afterTier);
    return { subtotal, tier_discount, coupon_discount, net: afterTier - coupon_discount };
  }

  discount(amount: number): number {
    if (this.coupon.startsWith("PCT")) {
      return Math.floor((2 * amount * Number(this.coupon.slice(3)) + 100) / 200);
    }
    if (this.coupon.startsWith("FIXED")) {
      return Math.min(Number(this.coupon.slice(5)) * 100, amount);
    }
    return 0;
  }

  resultFields(lines: Line[], amounts: Amounts, shipping: number, tax: number) {
    return {
      lines,
      subtotal: amounts.subtotal,
      tier_discount: amounts.tier_discount,
      coupon_discount: amounts.coupon_discount,
      shipping,
      tax,
      total: amounts.net + shipping + tax,
      applied: this.appliedNames(amounts, shipping, tax),
    };
  }

  appliedNames(amounts: Amounts, shipping: number, tax: number): string[] {
    const active = [
      [amounts.tier_discount > 0, "tier"],
      [amounts.coupon_discount > 0, "coupon"],
      [shipping === 0, "free-shipping"],
      [tax > 0, "tax"],
    ] as const;
    return active.filter(([enabled]) => enabled).map(([, name]) => name);
  }
}
