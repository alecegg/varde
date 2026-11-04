import { describe, expect, it } from 'vitest';
import { approvalBody, isMergeReady, validateNote } from './mergeApproval.ts';

describe('merge approval helpers', () => {
  it('only enables approval for pending non-terminal plans', () => {
    expect(isMergeReady({ id: 'p', status: 'active', awaiting_user: 'Merge?', merge_state: 'absent' })).toBe(true);
    expect(isMergeReady({ id: 'p', status: 'done', awaiting_user: 'Merge?' })).toBe(false);
    expect(isMergeReady({ id: 'p', status: 'active', awaiting_user: null })).toBe(false);
    expect(isMergeReady({ id: 'p', status: 'active', awaiting_user: 'Merge?', merge_state: 'approved_not_merged' })).toBe(false);
  });
  it('validates and builds optional note bodies', () => {
    expect(validateNote('x'.repeat(500))).toBeNull();
    expect(validateNote('x'.repeat(501))).toContain('500');
    expect(approvalBody('  ok  ')).toEqual({ note: 'ok' });
    expect(approvalBody(' ')).toEqual({ note: null });
  });
});
