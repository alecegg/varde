import { describe, expect, it } from 'vitest';
import { commentKind, commentState } from './planComments.ts';

describe('plan comment display', () => {
  it('maps API delivery and saved kinds honestly', () => {
    expect(commentKind('sent')).toBe('delivered');
    expect(commentKind('delivered')).toBe('delivered');
    expect(commentKind('stored')).toBe('saved');
    expect(commentKind(undefined)).toBe('saved');
  });

  it('keeps open and resolved states distinct', () => {
    expect(commentState('open')).toBe('open');
    expect(commentState('resolved')).toBe('resolved');
    expect(commentState('addressed')).toBe('open');
  });
});
