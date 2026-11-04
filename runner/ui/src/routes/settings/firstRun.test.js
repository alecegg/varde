import { describe, expect, it } from 'vitest';
import { checklistSteps, stepLink } from './firstRun.ts';

const pending = [
  { id: 'data_root', done: false, hint: 'Set the runner data root.', link: '/settings' },
  { id: 'service', done: false, hint: 'Install the runner service.', link: '/settings' },
  { id: 'harness', done: false, hint: 'Enable and log in to a harness.', link: '/settings' },
  { id: 'roles', done: true, hint: 'Enable the harnesses used by default roles.', link: '/roles' },
];

function doneById(steps) {
  return Object.fromEntries(steps.map((step) => [step.id, step.done]));
}

describe('first run links', () => {
  it('maps checklist steps to real controls', () => {
    expect(['data_root', 'service', 'harness', 'roles'].map((id) => stepLink({ id, link: '/settings' }))).toEqual(['#runner', '#runner', '#harnesses', '/roles']);
  });
});

describe('first run checklist ticks', () => {
  it('ticks a harness step when a harness is enabled, even before its login is known', () => {
    const steps = checklistSteps({
      checklist: pending,
      data_root: '/home/alec/.varde',
      harnesses: [{ enabled: true, binary_found: true, login: 'unknown' }],
    });
    expect(doneById(steps)).toMatchObject({ data_root: true, harness: true, roles: true, service: false });
  });

  it('leaves the harness step pending without an enabled harness', () => {
    const steps = checklistSteps({ checklist: pending, harnesses: [{ enabled: false, binary_found: true, login: 'ready' }] });
    expect(doneById(steps).harness).toBe(false);
  });

  it('leaves the harness step pending when the enabled harness cannot run', () => {
    expect(doneById(checklistSteps({ checklist: pending, harnesses: [{ enabled: true, binary_found: false, login: 'missing' }] })).harness).toBe(false);
    expect(doneById(checklistSteps({ checklist: pending, harnesses: [{ enabled: true, login: 'missing' }] })).harness).toBe(false);
  });

  it('ticks the service step for a managed or installed service', () => {
    expect(doneById(checklistSteps({ checklist: pending, service: { installed: true } })).service).toBe(true);
    expect(doneById(checklistSteps({ checklist: pending, service: { managed: true } })).service).toBe(true);
  });

  it('keeps backend-only steps and never clears a ticked step', () => {
    const steps = checklistSteps({ checklist: [{ ...pending[3], done: true }] });
    expect(steps).toEqual([{ ...pending[3], done: true }]);
    expect(checklistSteps({})).toEqual([]);
  });
});
