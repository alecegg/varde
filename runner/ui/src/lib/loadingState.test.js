import { describe, expect, it } from 'vitest';
import { loadingView } from './loadingState.ts';

describe('loadingView', () => {
  it('shows a placeholder while the first request is pending', () => {
    expect(loadingView(true, false)).toBe('skeleton');
  });

  it('keeps cached or refreshed data visible during revalidation', () => {
    expect(loadingView(true, true)).toBe('content');
  });

  it('shows an empty state only after the first request settles', () => {
    expect(loadingView(false, false)).toBe('empty');
  });
});
