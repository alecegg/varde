import { getHome } from '../homeApi';
import { chatChips, needsYouTotal, statusLine, type ChatChip, type ManagerChip } from './chatChips';
import { refreshWhenVisible } from '../refresh';

export type ShellData = {
  chips: ChatChip[];
  needsYouTotal: number;
  statusLine: string;
};

export async function loadShellData(): Promise<ShellData> {
  const [home, rolesResult] = await Promise.allSettled([
    getHome(),
    fetch('/api/roles', { cache: 'no-store' }).then((response) => response.ok ? response.json() : null),
  ]);
  const summaries = home.status === 'fulfilled' ? home.value.roles : [];
  const roleEnabled = rolesResult.status === 'fulfilled' && rolesResult.value
    ? rolesResult.value.roles?.['manager-bot']?.enabled === true
    : null;
  const manager = summaries.find((summary) => summary.role === 'manager-bot');
  const managerChip: ManagerChip = {
    id: 'manager', label: 'Manager', threadKey: 'main', roleEnabled,
    ...(manager ? { state: manager.state, queued: manager.queued, needs_you: manager.needs_you } : {}),
  };
  const chips = chatChips(summaries.filter((summary) => summary.role !== 'manager-bot'), managerChip);
  return { chips, needsYouTotal: needsYouTotal(chips), statusLine: statusLine(chips) };
}

export function watchShellData(update: (data: ShellData) => void): () => void {
  let active = true;
  const refresh = () => { void loadShellData().then((data) => { if (active) update(data); }).catch(() => {}); };
  refresh();
  window.addEventListener('runner:snapshot', refresh);
  const stopVisibleRefresh = refreshWhenVisible(refresh);
  return () => { active = false; window.removeEventListener('runner:snapshot', refresh); stopVisibleRefresh(); };
}
