type Item = { price: number; qty: number };

const TAX_RATE = 0.08;
const DISCOUNT_THRESHOLD = 100;
const DISCOUNT_RATE = 0.1;

const qtyOf = (item: Item): number => item.qty;
const priceOf = (item: Item): number => item.price;
const checkQty = (qty: number): boolean => qty > 0;
const checkPrice = (price: number): boolean => price >= 0;
const itemOk = (item: Item): boolean => checkQty(qtyOf(item)) && checkPrice(priceOf(item));
const allOk = (items: Item[]): boolean => items.every(itemOk);

function validate(items: Item[]): void {
  if (!allOk(items)) throw new Error("invalid item");
}

const mul = (a: number, b: number): number => a * b;
const lineTotal = (item: Item): number => mul(priceOf(item), qtyOf(item));
const add = (a: number, b: number): number => a + b;
const sumAll = (values: number[]): number => values.reduce(add, 0);
const subtotalOf = (items: Item[]): number => sumAll(items.map(lineTotal));
const gt = (a: number, b: number): boolean => a > b;
const discountApplies = (subtotal: number): boolean => gt(subtotal, DISCOUNT_THRESHOLD);
const applyRate = (amount: number, rate: number): number => amount * rate;
const discountFor = (subtotal: number): number =>
  discountApplies(subtotal) ? applyRate(subtotal, DISCOUNT_RATE) : 0;
const taxableOf = (subtotal: number, discount: number): number => subtotal - discount;
const round2 = (value: number): number => Math.round(value * 100) / 100;
const taxFor = (taxable: number): number => round2(applyRate(taxable, TAX_RATE));

function assemble(subtotal: number, discount: number, tax: number) {
  const total = round2(taxableOf(subtotal, discount) + tax);
  return { subtotal: round2(subtotal), discount: round2(discount), tax, total };
}

export function priceOrder(items: Item[]) {
  validate(items);
  const subtotal = subtotalOf(items);
  const discount = discountFor(subtotal);
  const tax = taxFor(taxableOf(subtotal, discount));
  return assemble(subtotal, discount, tax);
}
