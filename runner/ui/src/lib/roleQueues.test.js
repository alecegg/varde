import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { blockedReason, budgetPercent, budgetTone, duration, expiryLabel, itemTone } from './roleQueues.ts';

// Mirrors GET /api/queue/roles: asdict(QueueItem) rows, asdict(budget), asdict(LaneMetrics).
const ITEM_DEFAULTS = {
  plan_dir: '/source/plans/demo',
  findings: '',
  owned_files: '',
  depends_cell: '',
  depends_on: [],
  serialize_with: [],
  priority: 0,
  state: 'queued',
  planned_at: null,
  plan_reviewed_at: null,
  build_started_at: null,
  build_done_at: null,
  merged_at: null,
  role: 'builder',
  queue_name: 'default',
  row_order: 0,
  extra: { kind: 'task', inputs: {} },
  claimed_by: null,
  claim_expires_at: null,
  claim_generation: 0,
  claim_epoch: null,
};

function item(overrides) {
  return { ...ITEM_DEFAULTS, ...overrides };
}

const FIXTURE = {
  roles: [
    {
      role: 'builder',
      queued: 2,
      claimed: 2,
      ready: 2,
      items: [
        item({ id: '01-route', state: 'merged', merged_at: '2030-01-01T00:00:00Z' }),
        item({ id: '02-ui', state: 'claimed', claimed_by: 'builder-1', claim_expires_at: '2030-01-01T00:10:00Z', depends_on: ['01-route'] }),
        item({ id: '03-tests', state: 'queued', depends_on: ['01-route', '04-data'] }),
        item({ id: '04-data', state: 'building', claimed_by: 'builder-2' }),
        item({ id: '05-docs', state: 'queued', serialize_with: ['04-data'] }),
        item({ id: '06-clean', state: 'queued', depends_on: ['01-route'] }),
      ],
    },
  ],
  budget: {
    snapshot: {
      taken_at: '2030-01-01T00:00:00Z',
      providers: { anthropic: 0.4 },
      rss_mb: 1024.0,
      cpu_pct: 25.0,
      processes: 10,
      live_workers: 2,
    },
    limits: {
      provider_max: { anthropic: 0.8 },
      rss_mb_max: 4096.0,
      cpu_pct_max: 90.0,
      processes_max: 32,
      global_worker_ceiling: 4,
    },
    decision: { ok: true, reason: 'budget available' },
  },
  metrics: {
    cycle_seconds: { '01-route': 3600.0, '02-ui': null },
    idle_seconds: { 'builder-1': 125.0 },
  },
};

const STATES = new Map(FIXTURE.roles.flatMap((lane) => lane.items.map((row) => [row.id, row.state])));
const byId = (id) => FIXTURE.roles.flatMap((lane) => lane.items).find((row) => row.id === id);

test('formats durations for lane cycle and idle values', () => {
  assert.equal(duration(FIXTURE.metrics.cycle_seconds['01-route']), '1h');
  assert.equal(duration(FIXTURE.metrics.idle_seconds['builder-1']), '2m 5s');
  assert.equal(duration(FIXTURE.metrics.cycle_seconds['02-ui']), '—');
  assert.equal(duration(42), '42s');
});

test('bounds budget bars from the route fractions', () => {
  const { snapshot, limits } = FIXTURE.budget;
  assert.equal(budgetPercent(snapshot.providers.anthropic * 100, limits.provider_max.anthropic * 100), 50);
  assert.equal(budgetPercent(snapshot.rss_mb * 2, limits.rss_mb_max), 50);
  assert.equal(budgetPercent(120, 90), 100);
  assert.equal(budgetPercent(10, 0), null);
});

test('derives blocked reasons from the route item fields', () => {
  assert.equal(blockedReason(byId('06-clean'), STATES), null);
  assert.equal(blockedReason(byId('03-tests'), STATES), 'Depends on unmerged item 04-data');
  assert.equal(blockedReason(byId('05-docs'), STATES), 'Serialized with in-flight item 04-data');
  assert.equal(blockedReason(byId('02-ui'), STATES), null, 'claimed items are not queued blockers');
});

test('maps items and budget decisions to tones Badge accepts', () => {
  const badgeSource = readFileSync(new URL('./ui/Badge.svelte', import.meta.url), 'utf8');
  const union = /tone\?:([^;]+);/.exec(badgeSource)?.[1] ?? '';
  const allowed = new Set(union.split('|').map((tone) => tone.trim().replaceAll("'", '')));
  assert.ok(allowed.size > 0, 'could not read the Badge tone union');

  const tones = {
    blocked: itemTone(byId('03-tests'), blockedReason(byId('03-tests'), STATES)),
    ready: itemTone(byId('06-clean'), blockedReason(byId('06-clean'), STATES)),
    claimed: itemTone(byId('02-ui'), null),
    merged: itemTone(byId('01-route'), null),
    budgetOk: budgetTone(FIXTURE.budget.decision.ok),
    budgetBlocked: budgetTone(false),
  };
  assert.deepEqual(tones, { blocked: 'blocked', ready: 'success', claimed: 'waiting', merged: 'neutral', budgetOk: 'success', budgetBlocked: 'blocked' });
  for (const tone of Object.values(tones)) assert.ok(allowed.has(tone), `Badge has no ${tone} tone`);
});

test('formats claim lease expiry', () => {
  const lease = byId('02-ui').claim_expires_at;
  assert.equal(expiryLabel(lease, Date.parse('2030-01-01T00:09:30Z')), 'Lease 30s left');
  assert.equal(expiryLabel(lease, Date.parse('2030-01-01T00:20:00Z')), 'Lease expired');
  assert.equal(expiryLabel(null), 'No lease expiry');
  assert.equal(expiryLabel('invalid'), 'Lease expiry unavailable');
});
