const harnessNames: Record<string, string> = {
  'claude-cli': 'Claude Code (terminal)',
  'claude-sdk': 'Claude Code',
  'pi-rpc': 'Pi (local)',
  'pi-durable': 'Pi (persistent sessions)',
  'codex-app-server': 'Codex',
  'opencode-http': 'OpenCode',
};

export function displayHarnessName(value: string): string {
  const key = value.toLowerCase().replace(/[\s_-]+/g, '-');
  return harnessNames[key] ?? key.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function displayChoiceName(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
