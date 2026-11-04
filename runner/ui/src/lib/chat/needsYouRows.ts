import { listAgents, type Agent } from '../agentsApi.ts';
import { loadThreads, type ThreadMail } from '../mail/thread.ts';

export type NeedsYouRow =
  | { kind: 'thread'; value: ThreadMail; decision: Record<string, unknown> }
  | { kind: 'permission'; value: { agent: Agent; request: Agent['pending_requests'][number] } };

export function needsYouRows(threads: ThreadMail[], agents: Agent[], resolvedRequestIds: Set<string> = new Set()): NeedsYouRow[] {
  const pendingRequests = new Set(
    agents.flatMap((agent) => agent.capabilities.respond
      ? agent.pending_requests.map((request) => request.request_id)
      : []),
  );
  const seenRequests = new Set<string>();
  const mailboxRows = threads.flatMap((value) => value.decisions.flatMap((decision) => {
    if (!decision.mailbox_open || typeof decision.msg_id !== 'string' || !decision.msg_id) return [];
    const requestId = decision.kind === 'permission' && typeof decision.request_id === 'string'
      ? decision.request_id
      : '';
    if (requestId && (pendingRequests.has(requestId) || seenRequests.has(requestId) || resolvedRequestIds.has(requestId))) return [];
    if (requestId) seenRequests.add(requestId);
    return [{ kind: 'thread' as const, value, decision }];
  }));
  const permissionRows = agents.flatMap((agent) => agent.capabilities.respond
    ? agent.pending_requests.flatMap((request) => {
      if (seenRequests.has(request.request_id) || resolvedRequestIds.has(request.request_id)) return [];
      seenRequests.add(request.request_id);
      return [{ kind: 'permission' as const, value: { agent, request } }];
    })
    : []);
  return [...mailboxRows, ...permissionRows];
}

export async function loadNeedsYouRows(): Promise<NeedsYouRow[]> {
  const [threads, agents] = await Promise.all([loadThreads(), listAgents()]);
  return needsYouRows(threads, agents);
}
