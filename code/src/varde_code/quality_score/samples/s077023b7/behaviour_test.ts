import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

const file = process.env.SAMPLE_MODULE_PATH ?? 'original.ts';
const mod = await import(pathToFileURL(file.startsWith('/') ? file : `${process.cwd()}/${file}`).href);
const { createInvoice, renderInvoice } = mod;

test('subscription invoice behavior', () => {
  const a = createInvoice({ customerId: 'c-1', period: '2026-01', plan: 'basic', units: 100, credits: 0, taxRate: 0.1 });
  assert.equal(a.base, 20);
  assert.equal(a.includedUnits, 100);
  assert.equal(a.units, 100);
  assert.equal(a.overage, 0);
  assert.equal(a.credits, 0);
  assert.equal(a.taxable, 20);
  assert.equal(a.tax, 2);
  assert.equal(a.total, 22);
  const b = createInvoice({ customerId: 'z/opaque', period: 'P2', plan: 'plus', units: 520, credits: 5, taxRate: 0.2 });
  assert.equal(b.overage, 2);
  assert.equal(b.taxable, 47);
  assert.equal(b.tax, 9.4);
  assert.equal(b.total, 56.4);
  const c = createInvoice({ customerId: 'c', period: 'p', plan: 'max', units: 0, credits: 200, taxRate: 0 });
  assert.equal(c.credits, 100);
  assert.equal(c.taxable, 0);
  assert.equal(c.total, 0);
  const d = createInvoice({ customerId: 'c', period: 'p', plan: 'basic', units: 103, credits: 0.5, taxRate: 0.075 });
  assert.equal(d.overage, 0.3);
  assert.equal(d.taxable, 19.8);
  assert.equal(d.tax, 1.49);
  assert.equal(d.total, 21.29);
  assert.equal(renderInvoice(b), [
    'Invoice: z/opaque', 'Period: P2', 'Plan: plus', 'Base: $50.00',
    'Usage: 520 units ($2.00)', 'Credits: -$5.00', 'Tax: $9.40', 'Total: $56.40'
  ].join('\n'));
  for (const input of [
    { customerId: '', period: 'p', plan: 'basic', units: 1, credits: 0, taxRate: 0 },
    { customerId: 'c', period: ' ', plan: 'basic', units: 1, credits: 0, taxRate: 0 },
    { customerId: 'c', period: 'p', plan: 'other', units: 1, credits: 0, taxRate: 0 },
    { customerId: 'c', period: 'p', plan: 'basic', units: -1, credits: 0, taxRate: 0 },
    { customerId: 'c', period: 'p', plan: 'basic', units: 1.2, credits: 0, taxRate: 0 },
    { customerId: 'c', period: 'p', plan: 'basic', units: 1, credits: -1, taxRate: 0 },
    { customerId: 'c', period: 'p', plan: 'basic', units: 1, credits: 0, taxRate: 1.01 },
    { customerId: 'c', period: 'p', plan: 'basic', units: 1, credits: 0, taxRate: NaN },
  ]) assert.throws(() => createInvoice(input), TypeError);
});
