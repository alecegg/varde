import { priceOrder } from "./candidate.ts";

const result = priceOrder([{ price: 60, qty: 2 }]);
if (JSON.stringify(result) !== JSON.stringify({ subtotal: 120, discount: 12, tax: 8.64, total: 116.64 })) throw new Error("wrong total");
let rejected = false;
try { priceOrder([{ price: 10, qty: 0 }]); } catch { rejected = true; }
if (!rejected) throw new Error("zero quantity must be rejected");
