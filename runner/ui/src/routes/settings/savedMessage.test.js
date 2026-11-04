import { describe, expect, it } from 'vitest';
import { savedMessage } from './savedMessage.ts';

describe('advanced setting save confirmation', () => {
  it('shows a plain saved message when no restart is required', () => {
    expect(savedMessage({ restart_required: false })).toBe('Saved');
  });

  it('tells the user to restart when the save requires one', () => {
    expect(savedMessage({ restart_required: true })).toBe('Saved. Restart the runner to apply it.');
  });
});
