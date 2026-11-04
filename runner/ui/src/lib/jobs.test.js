import test from 'node:test';
import assert from 'node:assert/strict';
import { anyJobRunning, displayCost, displayDate, jobCardStatus, jobStateTone, lastRunStatusDiffers, orderJobs, sweepSummary } from './jobs.ts';

const job = (key, state) => ({ key, title: key, state, enabled: state !== 'paused', spends_model_usage: false, run_budget_usd: null, schedule_time: '03:00', next_run_at: null, last_run: null });

test('jobs needing attention sort ahead of ordinary jobs', () => {
  assert.deepEqual(orderJobs([job('zeta', 'succeeded'), job('paused', 'paused'), job('failed', 'failed')]).map(({ key }) => key), ['failed', 'paused', 'zeta']);
});

test('job state and usage values have readable presentations', () => {
  assert.equal(jobStateTone('failed'), 'blocked');
  assert.equal(jobStateTone('succeeded'), 'success');
  assert.equal(displayCost(0.125), '$0.1250');
  assert.equal(displayCost(null), 'Not reported');
  assert.equal(displayDate(null), 'Not scheduled');
});

test('polling is wanted only while a job is running', () => {
  assert.equal(anyJobRunning([job('a', 'succeeded'), job('b', 'running')]), true);
  assert.equal(anyJobRunning([job('a', 'succeeded'), job('b', 'failed')]), false);
});

test('sweep summary uses singular labels for one warning or failure', () => {
  assert.equal(sweepSummary(0, 1), 'Sweep: 0 warnings · 1 session failure.');
  assert.equal(sweepSummary(1, 2), 'Sweep: 1 warning · 2 session failures.');
});

test('job card status explains a successful sweep with session failures', () => {
  const sweep = { ...job('sweep', 'succeeded'), failures: [{}], last_run: { outcome: 'succeeded' } };
  assert.deepEqual(jobCardStatus(sweep), { status: 'succeeded', label: 'Completed with 1 session failure' });
  assert.equal(lastRunStatusDiffers(sweep), false);
  assert.equal(lastRunStatusDiffers({ ...sweep, state: 'paused' }), true);
});
