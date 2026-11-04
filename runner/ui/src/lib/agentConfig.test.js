import { describe, expect, it } from 'vitest';
import { effectiveConfig, summaryRows } from './agentConfig.ts';

const roles = {
  worker: { type: 'fast', harness: 'pi', model: 'model-a', reasoning_effort: 'high' },
};
const types = { fast: { harness: 'codex-app-server', model: 'model-b', reasoning_effort: 'medium' } };

describe('effectiveConfig', () => {
  it('returns null for a null role', () => {
    expect(effectiveConfig(null, roles, types)).toBeNull();
  });

  it('returns null when the role has no config', () => {
    expect(effectiveConfig('missing', roles, types)).toBeNull();
  });

  it('uses the referenced type config and type name', () => {
    expect(effectiveConfig('worker', roles, types)).toEqual({
      harness: 'codex-app-server', model: 'model-b', effort: 'medium', type: 'fast',
    });
  });

  it('uses role config and roleType fallback when its type is missing', () => {
    expect(effectiveConfig('worker', { worker: { ...roles.worker, type: 'gone' } }, {})).toEqual({
      harness: 'pi', model: 'model-a', effort: 'high', type: '',
    });
  });
});

describe('summaryRows', () => {
  it('returns labeled values and uses Not set for missing values', () => {
    expect(summaryRows({ harness: 'pi', model: '', effort: 'high', type: 'fast' })).toEqual([
      ['Harness', 'pi'], ['Model', 'Not set'], ['Effort', 'high'], ['Role type', 'fast'],
    ]);
  });
});
