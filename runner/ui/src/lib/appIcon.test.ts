import { describe, expect, it } from 'vitest';
import { iconPath } from './appIcon';

describe('app icon paths', () => {
  it('uses the default asset root for slate bronze', () => {
    expect(iconPath('/favicon.svg', 'slate-bronze')).toBe('/favicon.svg');
  });

  it('uses the dark asset set for every icon link', () => {
    expect(iconPath('/apple-touch-icon.png', 'dark')).toBe('/icons/dark/apple-touch-icon.png');
    expect(iconPath('/manifest.webmanifest', 'dark')).toBe('/icons/dark/manifest.webmanifest');
  });
});
