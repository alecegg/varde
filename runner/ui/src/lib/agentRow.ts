import type { Agent } from './agentsApi';
import { stateMarker, type AgentStatusMarker } from './agentStatus';

export type AgentRow = {
  title: string;
  shortId: string;
  state: AgentStatusMarker;
};

const UNASSIGNED_ROLE = 'Unassigned role';
const RAW_ID = /^[0-9a-f]{24,}$/i;

export function shortId(agentId: string): string {
  return agentId.slice(0, 8);
}

export function workspaceName(workspace: string | null | undefined): string {
  const trimmed = (workspace ?? '').trim().replace(/[\\/]+$/, '');
  return trimmed.split(/[\\/]/).at(-1) ?? '';
}

export function cardTitle(agent: Agent): string {
  const role = agent.role?.trim() || UNASSIGNED_ROLE;
  const name = workspaceName(agent.workspace);
  if (!name || name === agent.agent_id || RAW_ID.test(name)) return role;
  return `${role}: ${name}`;
}

export function oneLine(agent: Agent): AgentRow {
  return {
    title: cardTitle(agent),
    shortId: shortId(agent.agent_id),
    state: stateMarker(agent),
  };
}
