import type { InstanceThread } from '../threadsApi';

const DEAD_STATES = new Set(['archived', 'completed', 'error', 'failed', 'stopped', 'terminated', 'cancelled']);

export type ConversationGroup = { thread: InstanceThread; instances: InstanceThread[] };

export function conversationGroups(threads: InstanceThread[], agents: { agent_id: string; pending_requests: { request_id: string }[] }[] = []): ConversationGroup[] {
  const pendingAgents = new Set(agents.filter(({ pending_requests }) => pending_requests.length > 0).map(({ agent_id }) => agent_id));
  const byRole = new Map<string, InstanceThread[]>();
  for (const thread of threads) {
    if (!thread.agent_id || DEAD_STATES.has(thread.state.toLowerCase()) && !pendingAgents.has(thread.agent_id)) continue;
    const key = thread.role.trim().toLocaleLowerCase() || thread.agent_id;
    byRole.set(key, [...(byRole.get(key) ?? []), thread]);
  }
  const hasPending = (thread: InstanceThread) => pendingAgents.has(thread.agent_id);
  return [...byRole.values()].map((instances) => {
    instances.sort((a, b) => Number(hasPending(b)) - Number(hasPending(a)) || (b.last_activity ?? '').localeCompare(a.last_activity ?? ''));
    return { thread: instances[0], instances };
  }).sort((a, b) => (b.thread.last_activity ?? '').localeCompare(a.thread.last_activity ?? ''));
}

export function liveConversationThreads(threads: InstanceThread[]): InstanceThread[] {
  return conversationGroups(threads).map(({ thread }) => thread);
}

export function conversationNeeds(instances: InstanceThread[], agents: { agent_id: string; pending_requests: { request_id: string }[] }[]): number {
  const ids = new Set(instances.map(({ agent_id }) => agent_id));
  const requests = new Set(agents.filter(({ agent_id }) => ids.has(agent_id)).flatMap(({ pending_requests }) => pending_requests.map(({ request_id }) => request_id)));
  return requests.size;
}

export function conversationLabel(thread: Pick<InstanceThread, 'agent_id' | 'role'>): string {
  const role = thread.role.trim() || thread.agent_id;
  return role.replace(/[-\s]+/g, ' ').replace(/(^|\s)\w/g, (part) => part.toUpperCase());
}

export function permissionTitle(sender: string, value: string, knownLabel?: string): string {
  const agent = knownLabel || senderName(sender);
  const rawCommand = /^(?:run|execute)\s+(?:command|tool)\s*:\s*(.+)$/is.exec(value.trim());
  if (!rawCommand) return value.trim() || `${agent} needs your attention`;
  const command = shortCommand(rawCommand[1]);
  return command ? `${agent} wants to run: ${command}` : `${agent} wants to run a command`;
}

export function senderName(sender: string): string {
  const slug = sender
    .replace(/^sender:/, '')
    .replace(/^varde-/, '')
    .replace(/-\d+$/, '')
    .replace(/[^a-zA-Z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  const words = slug.split('-').filter(Boolean);
  if (words.length === 0) return 'Agent';
  return words.map((word) => {
    const normalized = word.toLowerCase();
    if (normalized === 'ux') return 'UX';
    if (normalized === 'sdk') return 'SDK';
    return word.charAt(0).toUpperCase() + word.slice(1);
  }).join(' ');
}

export type PlanMailThread = {
  thread_id: string;
  plan_id: string | null;
  sender?: string;
  plan_title?: string;
  title: string;
  open_count: number;
  last_ts: string;
  last_preview: string;
  user_message?: boolean;
  stale_count?: number;
};

export function planPreview(thread: PlanMailThread): string {
  const title = thread.plan_title || thread.title || thread.plan_id || 'Plan';
  const preview = permissionTitle(thread.sender ?? '', thread.last_preview || thread.title, title);
  if (preview.trim().toLocaleLowerCase() === title.trim().toLocaleLowerCase()) {
    return thread.open_count > 0 ? 'Needs your response' : 'Review latest activity';
  }
  return preview;
}

export function visiblePlanThreads(threads: PlanMailThread[], now = Date.now()): PlanMailThread[] {
  const latestByPlan = new Map<string, PlanMailThread>();
  for (const thread of threads) {
    if (!thread.plan_id || thread.user_message !== true || (thread.stale_count ?? 0) > 0 && thread.open_count === 0) continue;
    const recent = Number.isFinite(Date.parse(thread.last_ts)) && Date.parse(thread.last_ts) > now - 2 * 86400000;
    if (!thread.open_count && !recent) continue;
    const previous = latestByPlan.get(thread.plan_id);
    if (!previous || thread.last_ts > previous.last_ts) latestByPlan.set(thread.plan_id, thread);
  }
  return [...latestByPlan.values()].sort((a, b) => b.last_ts.localeCompare(a.last_ts));
}

export function visibleSenderThreads(threads: PlanMailThread[], now = Date.now()): PlanMailThread[] {
  const latestBySender = new Map<string, PlanMailThread>();
  for (const thread of threads) {
    if (!thread.thread_id.startsWith('sender:') || (thread.stale_count ?? 0) > 0 && thread.open_count === 0) continue;
    if (thread.user_message !== true || Date.parse(thread.last_ts) <= now - 2 * 86400000) continue;
    const sender = (thread.sender || thread.thread_id.slice('sender:'.length)).replace(/^varde-/, '').replace(/-\d+$/, '').toLowerCase();
    const previous = latestBySender.get(sender);
    if (!previous || thread.last_ts > previous.last_ts) latestBySender.set(sender, thread);
  }
  return [...latestBySender.values()].sort((a, b) => b.last_ts.localeCompare(a.last_ts));
}

function shortCommand(command: string): string {
  const compact = command.replace(/\\\n/g, ' ').replace(/\s+/g, ' ').trim();
  const shell = /^\/bin\/(?:z|ba)?sh\s+-lc\s+(['"])(.*)\1$/s.exec(compact);
  const readable = shell?.[2] ?? compact.replace(/^(['"])([\s\S]*)\1$/, '$2');
  return readable.length > 72 ? `${readable.slice(0, 69)}…` : readable;
}
