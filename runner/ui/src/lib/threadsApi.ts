export type InstanceThread = {
  thread_key: string;
  agent_id: string;
  plan_id: string | null;
  role: string;
  label: string;
  state: string;
  last_activity: string | null;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.error === 'string' ? body.error : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function getInstanceThread(agentId: string): Promise<InstanceThread> {
  const result = await request<{ threads: InstanceThread[] }>(`/api/instance-threads?agent=${encodeURIComponent(agentId)}`);
  const thread = result.threads[0];
  if (!thread) throw new Error('Thread not found');
  return thread;
}

export async function getPlanThreads(planId: string): Promise<InstanceThread[]> {
  return (await request<{ threads: InstanceThread[] }>(`/api/instance-threads?plan=${encodeURIComponent(planId)}`)).threads;
}

export async function listInstanceThreads(): Promise<InstanceThread[]> {
  return (await request<{ threads: InstanceThread[] }>('/api/instance-threads')).threads;
}

export async function listInstanceWorkspaces(): Promise<Record<string, string>> {
  const agents = await request<{ agent_id: string; workspace: string | null }[]>('/api/agents');
  return Object.fromEntries(agents.flatMap(({ agent_id, workspace }) => workspace ? [[agent_id, workspace]] : []));
}

export function threadsForTask(
  task: { id: string; title: string },
  threads: InstanceThread[],
  workspaces: Record<string, string>,
): InstanceThread[] {
  const title = task.title.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const tokens = [task.id.toLowerCase(), title].filter(Boolean);
  return threads.filter((thread) => {
    const assignment = `${workspaces[thread.agent_id] ?? ''} ${thread.agent_id} ${thread.label}`.toLowerCase();
    return tokens.some((token) => assignment.includes(token));
  });
}
