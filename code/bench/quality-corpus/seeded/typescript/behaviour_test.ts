import test from 'node:test';
import assert from 'node:assert/strict';

const target = process.env.SAMPLE_MODULE_PATH ?? 'original.ts';
const moduleUrl = target.startsWith('file:') ? target : new URL(target, `file://${process.cwd()}/`).href;
const api = await import(moduleUrl);

const catalog = {
  A1: { price: 40, stock: 10 },
  B2: { price: 70, stock: 4 },
  C3: { price: 10.25, stock: 8 },
};

test('prices an order with cumulative discounts, tax, shipping, and report output', () => {
  const result = api.processOrder({ id: 'R1', items: [{ sku: 'A1', quantity: 2 }, { sku: 'C3', quantity: 2 }] }, catalog);
  assert.equal(result.id, 'R1');
  assert.deepEqual(result.items, [
    { sku: 'A1', quantity: 2, unitPrice: 40, lineTotal: 80 },
    { sku: 'C3', quantity: 2, unitPrice: 10.25, lineTotal: 20.5 },
  ]);
  assert.equal(result.subtotal, 100.5);
  assert.equal(result.discount, 10.05);
  assert.equal(result.tax, 7.24);
  assert.equal(result.shipping, 5);
  assert.equal(result.total, 102.69);
  assert.match(api.formatOrderReport(result), /^Order R1\n/);
  assert.match(api.formatOrderReport(result), /A1 x2: \$80\.00/);
  assert.match(api.formatOrderReport(result), /Subtotal: \$100\.50/);
  assert.match(api.formatOrderReport(result), /Discount: -\$10\.05/);
  assert.match(api.formatOrderReport(result), /Tax: \$7\.24/);
  assert.match(api.formatOrderReport(result), /Shipping: \$5\.00/);
  assert.match(api.formatOrderReport(result), /Total: \$102\.69/);
});

test('applies both thresholds and free shipping', () => {
  const result = api.processOrder({ id: 'R2', items: [{ sku: 'B2', quantity: 3 }] }, catalog);
  assert.equal(result.subtotal, 210);
  assert.equal(result.discount, 31.5);
  assert.equal(result.tax, 14.28);
  assert.equal(result.shipping, 0);
  assert.equal(result.total, 192.78);
});

test('selects lower shipping tiers and rounds each stage', () => {
  const low = api.processOrder({ id: 'R3', items: [{ sku: 'C3', quantity: 1 }] }, catalog);
  assert.equal(low.discount, 0);
  assert.equal(low.tax, 0.82);
  assert.equal(low.shipping, 12);
  assert.equal(low.total, 23.07);
  const mid = api.processOrder({ id: 'R4', items: [{ sku: 'A1', quantity: 2 }] }, catalog);
  assert.equal(mid.shipping, 5);
});

test('rejects invalid orders and catalog entries', () => {
  const rejects = (input, message, data = catalog) => assert.throws(() => api.processOrder(input, data), new RegExp(message, 'i'));
  rejects(null, 'order');
  rejects({ id: '', items: [{ sku: 'A1', quantity: 1 }] }, 'id');
  rejects({ id: 'R', items: [] }, 'items');
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 0 }] }, 'quantity');
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 1.5 }] }, 'quantity');
  rejects({ id: 'R', items: [{ sku: 'Z9', quantity: 1 }] }, 'unknown');
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 11 }] }, 'stock');
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 1 }, { sku: 'A1', quantity: 1 }] }, 'duplicate');
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 1 }] }, 'price', { A1: { price: 0, stock: 1 } });
  rejects({ id: 'R', items: [{ sku: 'A1', quantity: 1 }] }, 'stock', { A1: { price: 2, stock: -1 } });
});
