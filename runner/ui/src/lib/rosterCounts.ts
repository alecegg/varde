type RosterAgent = { role: string | null; lifecycle: string | null };
type RosterRole = { role: string };

export function rosterCounts(agents: RosterAgent[], roles: RosterRole[]): Record<string, number> {
  const counts = Object.fromEntries(roles.map(({ role }) => [role, 0]));
  for (const agent of agents) {
    if (agent.lifecycle === 'completed' || agent.lifecycle === 'archived') continue;
    const role = agent.role === 'manager-bot' ? 'manager' : agent.role;
    if (role && role in counts) counts[role] += 1;
    else if ('other' in counts) counts.other += 1;
  }
  return counts;
}
