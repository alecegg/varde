type DiffEntry = { key: string; before: unknown; after: unknown };

function displayKey(key: string): string {
  if (key === 'claude_sdk.enabled') return 'Claude Code integration';
  const harness = /^types\.([^.]+)\.harness$/.exec(key);
  if (!harness) return key;
  const type = harness[1].replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  return `${type} type harness`;
}

function displayValue(value: unknown): string {
  if (value === true) return 'on';
  if (value === false) return 'off';
  if (value === 'claude-cli') return 'Claude Code terminal';
  if (value === 'claude-sdk') return 'Claude Code integration';
  if (value === null || typeof value === 'string' || typeof value === 'number') return String(value);
  return JSON.stringify(value);
}

export function diffRows(diff: DiffEntry[]): string[] {
  return diff.map(({ key, before, after }) => `${displayKey(key)}: ${displayValue(before)} to ${displayValue(after)}`);
}
