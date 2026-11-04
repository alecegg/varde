import { describe, expect, it } from 'vitest';
import { choicesFor, emptyTypesMessage, fallbackMoveAnnouncement, harnessOptions, moveFallback, typeChanges, typesFromItems, unavailableChoiceHarnesses, validateFallbacks } from './types.ts';

describe('settings type editor data', () => {
  it('explains legacy configurations without model types', () => {
    expect(emptyTypesMessage).toBe('No model types in this configuration (legacy format). Saving role types converts it.');
  });

  it('builds options from the server choices schema', () => {
    const choices = { 'codex-app-server': { harnesses: ['codex-app-server'], models: ['gpt-6'], reasoning_efforts: ['high'] } };
    expect(harnessOptions(choices)).toEqual(['codex-app-server']);
    expect(choicesFor(choices, 'codex-app-server').models).toEqual(['gpt-6']);
    expect(choicesFor(choices, 'unknown').models).toEqual([]);
  });

  it('lists each harness with missing model or effort choices once', () => {
    const types = [{ name: 'standard', harness: 'missing', model: '', reasoning_effort: '', fallback: [{ harness: 'missing', model: '', reasoning_effort: '' }, { harness: 'ready', model: 'm', reasoning_effort: 'high' }] }];
    const choices = { missing: { harnesses: [], models: [], reasoning_efforts: [] }, ready: { harnesses: [], models: ['m'], reasoning_efforts: ['high'] } };
    expect(unavailableChoiceHarnesses(types, choices)).toEqual(['missing']);
  });

  it('reads type values and produces structured preview changes', () => {
    const types = typesFromItems([
      { key: 'types.standard.harness', value: 'codex-app-server' },
      { key: 'types.standard.model', value: 'gpt-6' },
      { key: 'types.standard.reasoning_effort', value: 'high' },
      { key: 'types.standard.fallback', value: [{ harness: 'pi', model: 'm', reasoning_effort: 'medium' }] },
    ]);
    expect(types[0].name).toBe('standard');
    expect(typeChanges(types)['types.standard.fallback']).toEqual(types[0].fallback);
  });

  it('reorders fallbacks without changing the original list or crossing its ends', () => {
    const fallbacks = [
      { harness: 'a', model: 'one', reasoning_effort: 'low' },
      { harness: 'b', model: 'two', reasoning_effort: 'high' },
    ];
    expect(moveFallback(fallbacks, 0, 1).map(({ harness }) => harness)).toEqual(['b', 'a']);
    expect(moveFallback(fallbacks, 0, -1)).toBe(fallbacks);
    expect(fallbacks.map(({ harness }) => harness)).toEqual(['a', 'b']);
  });

  it('announces the original and new fallback positions', () => {
    expect(fallbackMoveAnnouncement(3, 2)).toBe('Fallback 3 moved to position 2.');
  });

  it('validates each fallback field', () => {
    expect(validateFallbacks([
      { harness: '', model: 'm', reasoning_effort: 'high' },
      { harness: 'pi', model: '', reasoning_effort: 'high' },
      { harness: 'pi', model: 'm', reasoning_effort: '' },
      { harness: 'pi', model: 'm', reasoning_effort: 'high' },
    ])).toEqual(['Choose a harness.', 'Choose a model.', 'Choose an effort.', '']);
  });
});
