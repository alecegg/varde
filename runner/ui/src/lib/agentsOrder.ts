import { attentionOrder, type Agent } from './agentsApi';
export function stableOrder(next: Agent[], previousIds: string[]): Agent[] {
  const byId = new Map(next.map((agent) => [agent.agent_id, agent]));
  const retained = previousIds.flatMap((id) => byId.has(id) ? [byId.get(id)!] : []);
  const retainedIds = new Set(retained.map((agent) => agent.agent_id));
  return [...retained, ...attentionOrder(next.filter((agent) => !retainedIds.has(agent.agent_id)))];
}
