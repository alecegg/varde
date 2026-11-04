type Item = { price: number; qty: number };

const TAX_RATE = 0.08;
const DISCOUNT_THRESHOLD = 100;
const DISCOUNT_RATE = 0.1;

const round2 = (value: number): number => Math.round(value * 100) / 100;

function validateItems(items: Item[]): void {
  for (const { price, qty } of items) {
    if (qty <= 0 || price < 0) throw new Error("invalid item");
  }
}

export function priceOrder(items: Item[]) {
  validateItems(items);
  const subtotal = items.reduce((sum, { price, qty }) => sum + price * qty, 0);
  const discount = subtotal > DISCOUNT_THRESHOLD ? subtotal * DISCOUNT_RATE : 0;
  const taxable = subtotal - discount;
  const tax = round2(taxable * TAX_RATE);
  return {
    subtotal: round2(subtotal),
    discount: round2(discount),
    tax,
    total: round2(taxable + tax),
  };
}
