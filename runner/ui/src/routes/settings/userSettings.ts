import type { ConfigItem } from '../../lib/runnerConfigApi';

const configOnlySettings = new Set([
  'runner.require_user_pairing',
  'runner.idle_process_timeout_s',
]);

export function userSettings(items: ConfigItem[]): ConfigItem[] {
  return items.filter((item) => !configOnlySettings.has(item.key) && item.group !== 'bot');
}
