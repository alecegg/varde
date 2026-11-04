export type Agent = Record<string, unknown>;

const activityTime = (agent: Agent): number => {
  const activity = agent.lastActivity ?? agent.lastActivityAt ?? agent.last_activity ?? agent.updatedAt;
  return typeof activity === 'string' ? Date.parse(activity) : Number.NaN;
};

export function defaultVisibleAgents(agents: Agent[], now = Date.now(), limit = 10): Agent[] {
  const running = agents.filter((agent) => String(agent.status).toLowerCase() === 'running');
  const recent = agents
    .filter((agent) => String(agent.status).toLowerCase() !== 'running')
    .map((agent) => ({ agent, timestamp: activityTime(agent) }))
    .filter(({ timestamp }) => Number.isFinite(timestamp) && timestamp >= now - 24 * 60 * 60 * 1000)
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, limit)
    .map(({ agent }) => agent);
  return [...running, ...recent];
}
