import { openAgentWriter, respondAgent, type Agent, type AgentRequest } from './agentsApi';

export type HomeApproval = { agentId: string; request: AgentRequest };
export type ApprovalDecision = 'allow' | 'deny';

// The request a Home row shows while its role agent waits on the user. Reading
// this never answers anything; only a click on Allow or Deny does.
export function pendingApproval(agents: Agent[], agentId: string | null): HomeApproval | null {
  if (!agentId) return null;
  const agent = agents.find((candidate) => candidate.agent_id === agentId);
  if (!agent?.capabilities.respond) return null;
  const request = agent.pending_requests[0];
  return request ? { agentId: agent.agent_id, request } : null;
}

// Sends the decision the user clicked. Nothing else calls this, so approval
// authority stays with the user on the Home row.
export async function answerApproval(approval: HomeApproval, decision: ApprovalDecision): Promise<void> {
  const writer = await openAgentWriter(approval.agentId, () => {});
  try { await respondAgent(approval.agentId, writer, approval.request.request_id, decision); }
  finally { writer.close(); }
}
