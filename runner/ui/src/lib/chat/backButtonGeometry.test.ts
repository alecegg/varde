import { describe, expect, it } from 'vitest';
import { BACK_BUTTON_SIZE, backButtonGeometry } from './backButtonGeometry';

describe('shared back button geometry', () => {
  it('uses a 44px square with a centered icon', () => {
    expect(backButtonGeometry(BACK_BUTTON_SIZE, BACK_BUTTON_SIZE, 20, 20)).toEqual({
      width: 44,
      height: 44,
      iconLeft: 12,
      iconTop: 12,
    });
  });
});
