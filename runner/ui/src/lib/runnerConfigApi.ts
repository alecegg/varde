export type ConfigValue = boolean | number;
type ConfigItemFields = {
  key: string;
  label: string;
  hint: string;
  bounds: { min: number | null; max: number | null } | null;
  restart_required: boolean;
  group: 'harnesses' | 'limits' | 'bot' | string;
};
export type ConfigItem = ConfigItemFields & (
  | { type: 'boolean'; value: boolean; default: boolean }
  | { type: 'integer'; value: number; default: number }
);
export type ConfigGroup = { harnesses: ConfigItem[]; limits: ConfigItem[]; bot: ConfigItem[]; runner: ConfigItem[] };
export type ChecklistStep = { id: string; done: boolean; hint: string; link: string };
export type HarnessStatus = {
  name: string;
  enabled: boolean;
  binary_found: boolean;
  login: 'ready' | 'login_required' | 'missing' | 'unknown';
  hint: string;
};
export type RunnerStatus = {
  version: string;
  uptime_s: number;
  config_path: string;
  data_root: string;
  service: { managed: boolean; kind: string | null; installed?: boolean };
  harnesses: HarnessStatus[];
  checklist: ChecklistStep[];
};

export class ConfigApiError extends Error {
  readonly errors: Record<string, string>;

  constructor(message: string, errors: Record<string, string> = {}) {
    super(message);
    this.errors = errors;
  }
}

export function groupItems(items: ConfigItem[]): ConfigGroup {
  return {
    harnesses: items.filter((item) => item.group === 'harnesses'),
    limits: items.filter((item) => item.group === 'limits'),
    bot: items.filter((item) => item.group === 'bot'),
    runner: items.filter((item) => item.group === 'runner'),
  };
}

export function controlKind(item: ConfigItem): 'checkbox' | 'number' {
  return item.type === 'integer' ? 'number' : 'checkbox';
}

export function initialDraft(item: ConfigItem): string | boolean {
  return item.type === 'integer' ? String(item.value) : item.value;
}

export function validateValue(item: ConfigItem, value: string | boolean): string | null {
  if (item.type === 'boolean') return typeof value === 'boolean' ? null : 'Choose on or off.';
  if (typeof value !== 'string' || value.trim() === '') return 'Enter a whole number.';
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) return 'Enter a whole number.';
  if (item.bounds?.min !== null && item.bounds?.min !== undefined && parsed < item.bounds.min) {
    return `Must be at least ${item.bounds.min}.`;
  }
  if (item.bounds?.max !== null && item.bounds?.max !== undefined && parsed > item.bounds.max) {
    return `Must be at most ${item.bounds.max}.`;
  }
  return null;
}

export function restartNotice(required: boolean): string {
  return required ? 'Restart the runner to apply this change.' : '';
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const record = body && typeof body === 'object' ? body as Record<string, unknown> : {};
    const errors = record.errors && typeof record.errors === 'object' && !Array.isArray(record.errors)
      ? Object.fromEntries(Object.entries(record.errors).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
      : {};
    const message = typeof record.hint === 'string' ? record.hint
      : typeof record.error === 'string' ? record.error
      : `Request failed (${response.status})`;
    throw new ConfigApiError(message, errors);
  }
  return body as T;
}

export async function loadRunnerConfig(): Promise<ConfigItem[]> {
  return (await request<{ items: ConfigItem[] }>('/api/runner/config')).items;
}

export async function saveRunnerConfig(changes: Record<string, ConfigValue>): Promise<{ items: ConfigItem[]; restart_required: boolean }> {
  return request('/api/runner/config', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ changes }),
  });
}

export async function loadRunnerStatus(): Promise<RunnerStatus> {
  return request('/api/runner/status');
}

export async function restartRunner(): Promise<void> {
  await request('/api/runner/restart', { method: 'POST' });
}
