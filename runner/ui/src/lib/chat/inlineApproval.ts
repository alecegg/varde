import type { Agent, AgentRequest } from '../agentsApi';
import type { ChatMessage } from './chatState';

export type ThreadApproval = { agent: Agent; request: AgentRequest };
export type AnsweredApproval = Record<string, 'approved' | 'denied'>;

export function recordApprovalAnswer(answered: AnsweredApproval, key: string, decision: string): AnsweredApproval {
  return { ...answered, [key]: decision === 'allow' ? 'approved' : 'denied' };
}

export function answerForRequest(
  messages: Pick<ChatMessage, 'kind' | 'text' | 'role' | 'link'>[],
  requestId: string,
): 'approved' | 'denied' | undefined {
  const answer = messages.find((message) => {
    if (message.role !== 'event' || message.kind !== 'answer' || !message.link?.startsWith('request:')) return false;
    try { return decodeURIComponent(message.link.slice('request:'.length)) === requestId; }
    catch { return false; }
  });
  if (!answer) return undefined;
  return answer.text.toUpperCase().startsWith('APPROVED') ? 'approved' : 'denied';
}

export function approvalsForThread(threadKey: string, agents: Agent[]): ThreadApproval[] {
  const target = threadKey === 'main' ? null : threadKey.startsWith('instance:') ? threadKey.slice('instance:'.length) : undefined;
  if (target === undefined) return [];
  const seen = new Set<string>();
  return agents.flatMap((agent) => {
    const belongs = target === null ? agent.root_launched_by === 'bot:manager' : agent.agent_id === target;
    if (!belongs || !agent.capabilities.respond) return [];
    return agent.pending_requests.flatMap((request) => {
      if (seen.has(request.request_id)) return [];
      seen.add(request.request_id);
      return [{ agent, request }];
    });
  });
}
