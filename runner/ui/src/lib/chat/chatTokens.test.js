import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync(new URL('./chatTokens.css', import.meta.url), 'utf8');

function tokensFor(selector) {
  const block = source.match(new RegExp(`${selector}\\s*\\{([^}]+)\\}`))?.[1];
  expect(block, `missing ${selector} token block`).toBeTruthy();
  return Object.fromEntries(
    [...block.matchAll(/(--cf-[\w-]+)\s*:\s*(#[\da-fA-F]{3,8})/g)].map(([, key, value]) => [key, value]),
  );
}

function rgb(hex) {
  const normalized = hex.slice(1);
  const channels = normalized.length === 3
    ? [...normalized].map((channel) => Number.parseInt(channel + channel, 16))
    : [0, 2, 4].map((index) => Number.parseInt(normalized.slice(index, index + 2), 16));
  return channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
}

function contrast(first, second) {
  const luminance = (hex) => {
    const [red, green, blue] = rgb(hex);
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  };
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

const pairs = [
  ['body', '--cf-text', '--cf-bg', 4.5],
  ['muted', '--cf-muted', '--cf-panel', 4.5],
  ['primary-action text', '--cf-primary-ink', '--cf-primary', 4.5],
  ['primary button/card', '--cf-primary-ink', '--cf-primary', 4.5],
  ['secondary text', '--cf-text', '--cf-soft', 4.5],
  ['danger labels', '--cf-bad', '--cf-badbg', 4.5],
  ['disabled text', '--cf-muted', '--cf-bg', 4.5],
  ['disabled button/card', '--cf-muted', '--cf-soft', 4.5],
  ['needs label', '--cf-accent-ink', '--cf-accent', 4.5],
  ['needs glyph', '--cf-accent-ink', '--cf-accent', 3],
  ['count badge', '--cf-badge-ink', '--cf-badge', 4.5],
  ['mine bubble', '--cf-bg', '--cf-text', 4.5],
  ['theirs bubble', '--cf-text', '--cf-soft', 4.5],
  ['success state', '--cf-good', '--cf-goodbg', 4.5],
  ['denied state', '--cf-bad', '--cf-badbg', 4.5],
];

describe('chat design token contrast', () => {
  it.each([
    ['light', ':root'],
    ['dark', ':root\\[data-theme=dark\\]'],
  ])('keeps prototype text and background pairs accessible in %s theme', (_theme, selector) => {
    const tokens = tokensFor(selector);
    for (const [name, foreground, background, minimum] of pairs) {
      expect(contrast(tokens[foreground], tokens[background]), name).toBeGreaterThanOrEqual(minimum);
    }
  });
});
