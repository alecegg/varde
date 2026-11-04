import test from 'node:test';
import assert from 'node:assert/strict';
import { criterionPresentation, criterionValue, reportLoadMessage, requestStateForStatus, streakPresentation } from './mailSoak.ts';

const fixture = {
  date: '2026-10-23',
  window_days: 7,
  criteria: [
    { id: 'delivered-latency', value: 42, threshold: 120, ok: true, n: 8, insufficient: false },
    { id: 'main-nudges', value: 1, threshold: 0, ok: false, n: 7, insufficient: false },
  ],
  active_orchestrators: 2,
  all_ok: false,
  days_ok_streak: 2,
};

test('mail soak fixture exposes criteria, values, thresholds and streak', () => {
  assert.deepEqual(criterionPresentation(fixture.criteria[0]), {
    label: 'Typical delivery time (95th percentile)', measure: 'Actual: 42 s · Target: 2 min', status: 'Pass', tone: 'pass', note: '',
  });
  assert.deepEqual(criterionPresentation(fixture.criteria[1]), {
    label: 'Main nudges', measure: 'Actual: 1 nudge · Target: 0 nudges', status: 'Fail', tone: 'fail', note: '',
  });
  assert.equal(criterionValue(1, 'status-clean'), 'not clean');
  assert.equal(criterionValue(0, 'status-clean'), 'clean');
  assert.equal(criterionValue(1, 'merge-guard'), 'overdue');
  assert.equal(criterionValue(0, 'merge-guard'), 'none overdue');
  assert.equal(criterionValue(0.2, 'send-no-mailman'), '20%');
  assert.equal(criterionValue(0.02, 'send-no-mailman'), '2%');
  assert.equal(criterionPresentation({ id: 'send-no-mailman', value: 0.2, threshold: 0.02, ok: false, n: 5, insufficient: false }).label, 'Send without mailman');
  assert.equal(streakPresentation(fixture), 'Soak in progress · 2 of 3 passing days');
  assert.equal(streakPresentation({ all_ok: true, days_ok_streak: 1 }), 'Soak in progress · 1 of 3 passing days');
  assert.equal(streakPresentation({ all_ok: true, days_ok_streak: 3 }), 'Soak passed · 3 of 3 passing days');
});

test('insufficient criteria remain visibly unproven and neutral', () => {
  assert.deepEqual(criterionPresentation({ id: 'ack-latency', value: null, threshold: 1800, ok: true, n: 2, insufficient: true }), {
    label: 'Acknowledgement time (95th percentile)', measure: 'Actual: — · Target: 30 min', status: 'Not enough data', tone: 'neutral', note: 'Based on 2 checks.',
  });
});

test('latency formatting preserves sub-minute precision and formats seconds as seconds', () => {
  assert.equal(criterionValue(12.5, 'delivered-latency'), '12.5 s');
  assert.equal(criterionValue(59, 'ack-latency'), '59 s');
  assert.equal(criterionValue(90, 'ack-latency'), '1 min 30 s');
  assert.equal(criterionValue(1800, 'ack-latency'), '30 min');
});

test('mail soak request states distinguish missing reports from failures', () => {
  assert.equal(requestStateForStatus(404), 'missing');
  assert.equal(requestStateForStatus(503), 'error');
  assert.equal(requestStateForStatus(200), 'ok');
  assert.equal(reportLoadMessage('missing'), 'Mail soak report is not available yet.');
  assert.equal(reportLoadMessage('error'), 'Could not load the mail soak report. Check your connection and retry.');
});
