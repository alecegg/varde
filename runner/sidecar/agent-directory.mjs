export async function listAgents(client) {
  const page = await client.agents.list();
  return page.entries.map(({ agent, workspace }) => ({ agent, workspace }));
}

export function listWorkspaces(entries) {
  const workspaces = new Map();
  for (const { agent, workspace } of entries) {
    const id = workspace?.id ?? workspace?.workspaceId ?? agent?.workspaceId;
    const cwd = workspace?.cwd ?? agent?.cwd;
    if (typeof id !== "string" || typeof cwd !== "string" || workspaces.has(id)) continue;
    workspaces.set(id, { id, title: workspace?.displayName || workspace?.title || cwd, cwd });
  }
  return [...workspaces.values()];
}
