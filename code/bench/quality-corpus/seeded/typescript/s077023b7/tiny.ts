type Plan = "basic" | "plus" | "max";
type Input = {
  customerId: string;
  period: string;
  plan: Plan;
  units: number;
  credits: number;
  taxRate: number;
};
type Invoice = {
  customerId: string;
  period: string;
  plan: Plan;
  base: number;
  includedUnits: number;
  units: number;
  overage: number;
  credits: number;
  taxable: number;
  tax: number;
  total: number;
};
type Details = { price: number; allowance: number };
const catalog: Record<Plan, Details> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};
function r0(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}
function s0(v: unknown): boolean {
  return typeof v === "string";
}
function s1(v: string): string {
  return v.trim();
}
function s2(v: unknown): boolean {
  return s0(v) && s1(v).length > 0;
}
function p0(v: unknown): boolean {
  return v === "basic";
}
function p1(v: unknown): boolean {
  return v === "plus";
}
function p2(v: unknown): boolean {
  return v === "max";
}
function p3(v: unknown): boolean {
  return p0(v) || p1(v) || p2(v);
}
function n0(v: unknown): boolean {
  return typeof v === "number";
}
function n1(v: number): boolean {
  return Number.isInteger(v);
}
function n2(v: number): boolean {
  return v >= 0;
}
function n3(v: unknown): boolean {
  return n0(v) && n1(v as number) && n2(v as number);
}
function c0(v: unknown): boolean {
  return n0(v) && Number.isFinite(v) && n2(v as number);
}
function t0(v: unknown): boolean {
  return n0(v) && Number.isFinite(v);
}
function t1(v: number): boolean {
  return v >= 0 && v <= 1;
}
function t2(v: unknown): boolean {
  return t0(v) && t1(v as number);
}
function fail(k: string): never {
  throw new TypeError(`Invalid ${k}`);
}
function checkCustomer(v: unknown): asserts v is string {
  if (!s2(v)) fail("customerId");
}
function checkPeriod(v: unknown): asserts v is string {
  if (!s2(v)) fail("period");
}
function checkPlan(v: unknown): asserts v is Plan {
  if (!p3(v)) fail("plan");
}
function checkUnits(v: unknown): asserts v is number {
  if (!n3(v)) fail("units");
}
function checkCredits(v: unknown): asserts v is number {
  if (!c0(v)) fail("credits");
}
function checkTax(v: unknown): asserts v is number {
  if (!t2(v)) fail("taxRate");
}
function details(p: Plan): Details {
  return catalog[p];
}
function included(d: Details): number {
  return d.allowance;
}
function price(d: Details): number {
  return d.price;
}
function excess(u: number, a: number): number {
  return Math.max(0, u - a);
}
function usage(u: number, a: number): number {
  return excess(u, a) * 0.1;
}
function roundedUsage(u: number, a: number): number {
  return r0(usage(u, a));
}
function subtotal(b: number, o: number): number {
  return b + o;
}
function credit(c: number, s: number): number {
  return Math.min(r0(c), s);
}
function taxable(s: number, c: number): number {
  return r0(s - c);
}
function tax(v: number, rate: number): number {
  return r0(v * rate);
}
function total(v: number, x: number): number {
  const n = r0(v + x);
  return Object.is(n, -0) ? 0 : n;
}
function make(
  input: Input,
  d: Details,
  o: number,
  c: number,
  x: number,
  z: number,
  q: number,
): Invoice {
  return {
    customerId: input.customerId,
    period: input.period,
    plan: input.plan,
    base: r0(price(d)),
    includedUnits: included(d),
    units: input.units,
    overage: o,
    credits: c,
    taxable: x,
    tax: z,
    total: q,
  };
}
export function createInvoice(input: Input): Invoice {
  const v: any = input;
  const customerId = v?.customerId;
  const period = v?.period;
  const plan = v?.plan;
  const units = v?.units;
  const credits = v?.credits;
  const taxRate = v?.taxRate;
  checkCustomer(customerId);
  checkPeriod(period);
  checkPlan(plan);
  checkUnits(units);
  checkCredits(credits);
  checkTax(taxRate);
  const d = details(plan);
  const o = roundedUsage(units, included(d));
  const c = credit(credits, subtotal(price(d), o));
  const x = taxable(subtotal(price(d), o), c);
  const z = tax(x, taxRate);
  return make(
    { customerId, period, plan, units, credits, taxRate },
    d,
    o,
    c,
    x,
    z,
    total(x, z),
  );
}
function money(n: number): string {
  return `$${n.toFixed(2)}`;
}
function line(k: string, v: string): string {
  return `${k}: ${v}`;
}
function usageText(i: Invoice): string {
  return `${i.units} units (${money(i.overage)})`;
}
function row1(i: Invoice): string {
  return line("Invoice", i.customerId);
}
function row2(i: Invoice): string {
  return line("Period", i.period);
}
function row3(i: Invoice): string {
  return line("Plan", i.plan);
}
function row4(i: Invoice): string {
  return line("Base", money(i.base));
}
function row5(i: Invoice): string {
  return line("Usage", usageText(i));
}
function row6(i: Invoice): string {
  return line("Credits", `-${money(i.credits)}`);
}
function row7(i: Invoice): string {
  return line("Tax", money(i.tax));
}
function row8(i: Invoice): string {
  return line("Total", money(i.total));
}
function rows(i: Invoice): string[] {
  return [
    row1(i),
    row2(i),
    row3(i),
    row4(i),
    row5(i),
    row6(i),
    row7(i),
    row8(i),
  ];
}
function joinRows(r: string[]): string {
  return r.join("\n");
}
export function renderInvoice(invoice: Invoice): string {
  return joinRows(rows(invoice));
}
