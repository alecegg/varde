import { describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import { diffRows } from './sdkFlip.ts';

describe('SDK flip confirmation flow', () => {
  it('formats config changes as readable rows', () => {
    expect(diffRows([
      { key: 'types.review.harness', before: 'claude-cli', after: 'claude-sdk' },
      { key: 'claude_sdk.enabled', before: false, after: true },
    ])).toEqual([
      'Review type harness: Claude Code terminal to Claude Code integration',
      'Claude Code integration: off to on',
    ]);
  });

  it('closes the review on Escape and restores focus to its trigger', async () => {
    const source = await readFile(new URL('./SdkFlipCard.svelte', import.meta.url), 'utf8');
    expect(source).toContain("event.key === 'Escape' && preview");
    expect(source).toContain('void closeReview()');
    expect(source).toContain("document.querySelector<HTMLButtonElement>('[data-sdk-review-trigger]')?.focus()");
    expect(source).toContain('<svelte:window onkeydown={handleKeydown} />');
  });

  it('only invokes apply from the explicit confirm action after preview', async () => {
    const source = await readFile(new URL('./SdkFlipCard.svelte', import.meta.url), 'utf8');
    const preview = source.match(/async function openReview\(\)([\s\S]*?)\n  }/);
    const apply = source.match(/async function confirmApply\(\)([\s\S]*?)\n  }/);
    expect(preview?.[1]).not.toContain('/api/runner/config/sdk-flip/apply');
    expect(apply?.[1]).toContain("'/api/runner/config/sdk-flip/apply'");
    expect(apply?.[1]).toContain('confirm: true');
    expect(source).toContain('{#if preview}');
    expect(source).toContain('onclick={confirmApply}');
  });
});
