import { solution } from "./solution.ts";
import assert from "node:assert/strict";

type Item = { sku: string; qty: unknown; price: unknown };
type Request = { items: Item[]; tier: string; coupon: string; region: string };
type Result = Record<string, unknown>;
const item = (sku: string, qty: unknown, price: unknown): Item => ({ sku, qty, price });
const request = (items: Item[], tier = "basic", coupon = "", region = "EU"): Request => ({ items, tier, coupon, region });
const failure = (error: string, index: number | null): Result => ({ error, index });

// Separate BigInt arithmetic: parse decimal strings into cents and round from
// quotient/remainder only at contract-defined boundaries.
function halfUp(n: bigint, d: bigint): bigint { return (2n * n + d) / (2n * d); }
function oracle(input: Request): Result {
  if (!input.items.length) return failure("EMPTY_ORDER", null);
  if (input.items.length > 50) return failure("TOO_MANY_ITEMS", null);
  const checked: { sku: string; qty: number; cents: bigint }[] = [];
  for (let i = 0; i < input.items.length; i++) {
    const row = input.items[i], sku = typeof row.sku === "string" ? row.sku.trim().toUpperCase() : "";
    if (!/^[A-Z0-9-]{3,12}$/.test(sku)) return failure("BAD_SKU", i);
    if (typeof row.qty !== "number" || !Number.isInteger(row.qty) || row.qty < 1 || row.qty > 1000) return failure("BAD_QTY", i);
    if (typeof row.price !== "string" || !/^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(row.price)) return failure("BAD_PRICE", i);
    const [whole, fractional = ""] = row.price.split(".");
    const cents = BigInt(whole) * 100n + BigInt((fractional + "00").slice(0, 2));
    if (!cents) return failure("BAD_PRICE", i);
    checked.push({ sku, qty: row.qty, cents });
  }
  const merged = new Map<string, { qty: number; cents: bigint }>();
  for (let i = 0; i < checked.length; i++) {
    const row = checked[i], prior = merged.get(row.sku);
    if (!prior) { merged.set(row.sku, { qty: row.qty, cents: row.cents }); continue; }
    if (prior.cents !== row.cents) return failure("PRICE_CONFLICT", i);
    prior.qty += row.qty;
    if (prior.qty > 1000) return failure("BAD_QTY", i);
  }
  const tier = input.tier.trim().toLowerCase(), coupon = input.coupon.trim().toUpperCase(), region = input.region.trim().toUpperCase();
  if (!(tier === "basic" || tier === "silver" || tier === "gold")) return failure("BAD_TIER", null);
  if (!(coupon === "" || /^(PCT([1-9]|[1-4][0-9]|50)|FIXED([1-9]|[1-9][0-9]|[1-4][0-9]{2}|500)|FREESHIP)$/.test(coupon))) return failure("BAD_COUPON", null);
  if (!(region === "EU" || region === "US" || region === "ASIA")) return failure("BAD_REGION", null);
  const lines = [...merged.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([sku, v]) => ({ sku, qty: v.qty, unit_cents: Number(v.cents), line_cents: Number(v.cents * BigInt(v.qty)) }));
  const subtotal = lines.reduce((sum, line) => sum + BigInt(line.line_cents), 0n);
  const tierRate = tier === "gold" ? 1000n : tier === "silver" ? 500n : 0n;
  const tierDiscount = halfUp(subtotal * tierRate, 10000n), afterTier = subtotal - tierDiscount;
  let couponDiscount = 0n;
  if (coupon.startsWith("PCT")) couponDiscount = halfUp(afterTier * BigInt(coupon.slice(3)), 100n);
  if (coupon.startsWith("FIXED")) { const fixed = BigInt(coupon.slice(5)) * 100n; couponDiscount = fixed < afterTier ? fixed : afterTier; }
  const net = afterTier - couponDiscount;
  const config = region === "EU" ? [2000n, 800n, 10000n] : region === "US" ? [700n, 500n, 7500n] : [1000n, 1200n, 15000n];
  const [taxRate, baseShipping, threshold] = config, free = coupon === "FREESHIP" || net >= threshold;
  const shipping = free ? 0n : baseShipping, tax = halfUp(net * taxRate, 10000n), applied: string[] = [];
  if (tierDiscount > 0n) applied.push("tier");
  if (couponDiscount > 0n) applied.push("coupon");
  if (free) applied.push("free-shipping");
  if (tax > 0n) applied.push("tax");
  return { lines, subtotal: Number(subtotal), tier_discount: Number(tierDiscount), coupon_discount: Number(couponDiscount), shipping: Number(shipping), tax: Number(tax), total: Number(net + shipping + tax), applied };
}
function check(input: Request, expected = oracle(input)): void { assert.deepStrictEqual(solution(input), expected, JSON.stringify(input)); }

const maximumItems = Array.from({ length: 50 }, (_, i) => item(`SKU${String(i).padStart(2, "0")}`, i === 0 ? 999 : 1000, "999999.99"));
for (const [tier, coupon, region] of [["gold", "PCT50", "EU"], ["silver", "FIXED500", "US"], ["basic", "", "ASIA"], ["gold", "FREESHIP", "US"]]) {
  const input = request(maximumItems, tier, coupon, region);
  check(input, oracle(input));
}

// The contract's six transcribed examples plus its threshold tie example.
const WORKED: [Request, Result][] = [
  [request([item(" ab-12 ",2,"10.00"),item("CD-34",1,"5.50")],"Silver","","us"), {lines:[{sku:"AB-12",qty:2,unit_cents:1000,line_cents:2000},{sku:"CD-34",qty:1,unit_cents:550,line_cents:550}],subtotal:2550,tier_discount:128,coupon_discount:0,shipping:500,tax:170,total:3092,applied:["tier","tax"]}],
  [request([item("X1X",10,"20.00")],"gold","pct10","EU"), {lines:[{sku:"X1X",qty:10,unit_cents:2000,line_cents:20000}],subtotal:20000,tier_discount:2000,coupon_discount:1800,shipping:0,tax:3240,total:19440,applied:["tier","coupon","free-shipping","tax"]}],
  [request([item("aaa",3,"1.00"),item("AAA",4,"1")],"basic","FIXED5","ASIA"), {lines:[{sku:"AAA",qty:7,unit_cents:100,line_cents:700}],subtotal:700,tier_discount:0,coupon_discount:500,shipping:1200,tax:20,total:1420,applied:["coupon","tax"]}],
  [request([item("ZZZ",1,"0.01")],"silver"," freeship ","EU"), {lines:[{sku:"ZZZ",qty:1,unit_cents:1,line_cents:1}],subtotal:1,tier_discount:0,coupon_discount:0,shipping:0,tax:0,total:1,applied:["free-shipping"]}],
  [request([item("RND",1,"2.50")],"basic","","US"), {lines:[{sku:"RND",qty:1,unit_cents:250,line_cents:250}],subtotal:250,tier_discount:0,coupon_discount:0,shipping:500,tax:18,total:768,applied:["tax"]}],
  [request([item("CAP",1,"3.00")],"basic","FIXED500","US"), {lines:[{sku:"CAP",qty:1,unit_cents:300,line_cents:300}],subtotal:300,tier_discount:0,coupon_discount:300,shipping:500,tax:0,total:500,applied:["coupon"]}],
  [request([item("TIE",1,"0.05")],"silver","PCT10","EU"), oracle(request([item("TIE",1,"0.05")],"silver","PCT10","EU"))],
];
for (const [input, expected] of WORKED) check(input, expected);

const errors: [Request, Result][] = [
  [request([]),failure("EMPTY_ORDER",null)],[request([item("a",1,"1")]),failure("BAD_SKU",0)],[request([item("ABC",0,"1")]),failure("BAD_QTY",0)],[request([item("ABC",1,"1.234")]),failure("BAD_PRICE",0)],
  [request([item("ABC",1,"1"),item("abc",1,"2")]),failure("PRICE_CONFLICT",1)],[request([item("ABC",600,"1"),item("abc",500,"1.0")]),failure("BAD_QTY",1)],[request([item("ABC",500,"1"),item("abc",501,"1.00")]),failure("BAD_QTY",1)],
  [request([item("ABC",1,"1")],"platinum"),failure("BAD_TIER",null)],[request([item("ABC",1,"1")],"platinum","PCT0","MARS"),failure("BAD_TIER",null)],[request([item("ABC",1,"1")],"basic","PCT0"),failure("BAD_COUPON",null)],[request([item("ABC",1,"1")],"basic","","MARS"),failure("BAD_REGION",null)],
  [request([item("ABC",1,"0")]),failure("BAD_PRICE",0)],[request([item("ABC",1,"0.00")]),failure("BAD_PRICE",0)],[request([item("ABC",1,null)]),failure("BAD_PRICE",0)],
];
for (const n of [2,13]) errors.push([request([item("A".repeat(n),1,"1")]),failure("BAD_SKU",0)]);
for (const sku of ["AB_","AB ","ÄBC"]) errors.push([request([item(sku,1,"1")]),failure("BAD_SKU",0)]);
for (const qty of [1001,true,"1"]) errors.push([request([item("ABC",qty,"1")]),failure("BAD_QTY",0)]);
for (const price of ["0","0.00","1.234","abc","","1234567","1000000",".50",".5","1.","+1","-1"," 1","1 ","1 0","1,5","1a","1e3"]) errors.push([request([item("ABC",1,price)]),failure("BAD_PRICE",0)]);
for (const coupon of ["PCT0","PCT51","PCT07","FIXED0","FIXED501","FIXED05","PCT","PCTX","FIXED1A","PCT-5","PCT5.0","FIXED 5","OTHER"]) errors.push([request([item("ABC",1,"1")],"basic",coupon),failure("BAD_COUPON",null)]);
errors.push([request([item("ABC",1,"1")],"basic","","mars"),failure("BAD_REGION",null)]);
errors.push([request(Array.from({length:51},()=>item("ABC",1,"1")),"bad"),failure("TOO_MANY_ITEMS",null)]);
errors.push([request([item("ABC",1,"1"),item("BAD",0,"bad"),item("BAD",1,"1")]),failure("BAD_QTY",1)]);
errors.push([request([item("ABC",1,"1"),item("abc",1,"2"),item("bad",0,"1")]),failure("BAD_QTY",2)]);
errors.push([request([item("ABC",1,"1"),item("abc",0,"2")]),failure("BAD_QTY",1)]);
errors.push([request([item("ABC",1,"1")],"bad","PCT0","MARS"),failure("BAD_TIER",null)]);
errors.push([request([item("ABC",1,"1")],"basic","PCT0","MARS"),failure("BAD_COUPON",null)]);
errors.push([request([item("ABC",1,"1"),item("abc",1,"2")],"bad","PCT0","MARS"),failure("PRICE_CONFLICT",1)]);
errors.push([request([item("ABC",1,"1")],"basic","FREESHIPX"),failure("BAD_COUPON",null)]);
for (const [input, expected] of errors) check(input, expected);

// Merge totals, sort order, thresholds on net after tier and coupon, and traps.
for (const [a,b] of [[500,500],[999,1],[1000,1]]) check(request([item("MERGE",a,"1"),item("merge",b,"1")]));
check(request(Array.from({length:50},(_,i)=>item(`S${String(i).padStart(2,"0")}`,1,"1"))));
for (const region of ["EU","US","ASIA"]) for (const amount of ["74.99","75","99.99","100","149.99","150"]) check(request([item("BOUND",1,amount)],"silver","PCT1",region));
for (const [region, amount] of [["EU","100"],["US","75"],["ASIA","150"]]) check(request([item("SHIP",1,amount)],"basic","",region));
check(request([item("NET",1,"105.30")],"silver","PCT1","EU"));
check(request([item("ORD",1,"0.01")],"silver","","EU"));
for (const price of ["1.005","1.015","2.675","0.05","0.15"]) for (const tier of ["silver","gold"]) check(request([item("ROUND",1,price)],tier,"PCT7","EU"));
check(request([item("PCTX",1,"1"),item("FIXED1A",1,"1"),item("PCT-5",1,"1"),item("PCT5.0",1,"1"),item("FIXED 5",1,"1")]));
check(request([item("A-1",1,"1"),item("A01",1,"1"),item("A-01",1,"1"),item("A10",1,"1")]));
check(request([item("AB-12",1,"1,5"),item("CD-34",1,"1a"),item("EF-56",1,"1e3"),item("GH-78",1,"+1"),item("IJ-90",1,"-1"),item("KL-12",1,"1 0"),item("MN-34",1,"1."),item("OP-56",1,".5")]));

let seed = 20261017;
function rand(limit: number): number { seed = (Math.imul(seed,1664525)+1013904223) >>> 0; return seed % limit; }
const skus=["A-1","A1B","x9-y","SKU-7","ABC","Q-42","ab","ABCDEFGHIJKLM","AB_"," "];
const prices=["0.01","1","1.2","12.34","999999.99","0","1.234","bad","1234567","","1a","1e3","+1","-1","1 0","1.",".5"];
const tiers=["basic","silver","gold","platinum"," Silver "], coupons=["","PCT1","PCT7","PCT50","PCT0","PCT07","FIXED1","FIXED500","FIXED501","FREESHIP"," pct10 ","PCTX","FIXED1A","PCT-5","PCT5.0","FIXED 5"], regions=["EU","US","ASIA","MARS"," us "];
for(let i=0;i<4000;i++){const rows:Item[]=[];for(let j=0,n=rand(7);j<n;j++)rows.push(item(skus[rand(skus.length)],[1,2,10,999,1000,0,1001,true,1.5][rand(9)],prices[rand(prices.length)]));check(request(rows,tiers[rand(tiers.length)],coupons[rand(coupons.length)],regions[rand(regions.length)]));}
console.log(`order-quote: ${WORKED.length} worked examples, ${errors.length} errors, 4,000 seeded requests passed`);
