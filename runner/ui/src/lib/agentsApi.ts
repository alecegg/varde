export type AgentRequest = { request_id: string; kind: string; summary: string };

export type LaunchAgentInput = {
  harness: string;
  workspace: string;
  role: string;
  prompt: string;
  address?: { slot: string; plan?: string | null };
};

export type LaunchAgentResponse = { agent_id: string };
export type AgentHarnessCapabilities = Record<string, boolean>;
export type AgentCapabilities = {
  harnesses: Record<string, AgentHarnessCapabilities>;
  disabled: string[];
};

export type Agent = {
  agent_id: string;
  name?: string;
  harness: string;
  role: string | null;
  workspace: string | null;
  launched_by?: string | null;
  root_launched_by?: string | null;
  lifecycle: string | null;
  idle_status: string | null;
  capabilities: Record<string, boolean>;
  pending_requests: AgentRequest[];
};

export function attentionOrder(agents: Agent[]): Agent[] {
  return [...agents].sort((a, b) => priority(a) - priority(b));
}

function priority(agent: Agent): number {
  if (agent.lifecycle === 'archived') return 5;
  if (agent.pending_requests.length) return 0;
  if (agent.lifecycle === 'failed' || agent.lifecycle === 'rate_limited' || agent.idle_status === 'rate_limited') return 1;
  if (agent.lifecycle === 'running') return 2;
  if (agent.lifecycle === 'idle') return 3;
  if (agent.lifecycle === 'completed') return 4;
  return 3;
}

export async function listAgents(): Promise<Agent[]> {
  return request<Agent[]>('/api/agents');
}

export async function launchAgent(input: LaunchAgentInput): Promise<LaunchAgentResponse> {
  return request<LaunchAgentResponse>('/api/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function getAgentCapabilities(): Promise<AgentCapabilities> {
  const response = await request<Record<string, AgentHarnessCapabilities | string[]>>('/api/agents/capabilities');
  const { disabled = [], ...harnesses } = response;
  return { harnesses: harnesses as Record<string, AgentHarnessCapabilities>, disabled: disabled as string[] };
}

export type AgentWriter = { client: string; close: () => void };

export function openAgentWriter(agentId: string, onClose: (close: () => void) => void): Promise<AgentWriter> {
  const client = `dashboard-writer-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
  const query = new URLSearchParams({ client, role: 'writer' });
  const stream = new EventSource(`/api/agents/${encodeURIComponent(agentId)}/watch?${query}`);
  const close = () => stream.close();
  onClose(close);
  return new Promise((resolve, reject) => {
    stream.onopen = () => resolve({ client, close });
    stream.onerror = () => {
      close();
      reject(new Error('Agent writer connection failed'));
    };
  });
}

export function promptAgent(agentId: string, writer: AgentWriter, text: string): Promise<{ outcome: string }> {
  return write(agentId, 'prompt', writer, { text });
}

export function interruptAgent(agentId: string, writer: AgentWriter): Promise<{ outcome: string }> {
  return write(agentId, 'interrupt', writer, {});
}

export function respondAgent(agentId: string, writer: AgentWriter, request_id: string, decision: string): Promise<{ result: string }> {
  return write(agentId, 'respond', writer, { request_id, decision });
}

export function resumeAgent(agentId: string, writer: AgentWriter): Promise<Record<string, never>> {
  return write(agentId, 'resume', writer, {});
}

export function stopAgent(agentId: string, writer: AgentWriter): Promise<Record<string, never>> {
  return write(agentId, 'stop', writer, {});
}

export function archiveAgent(agentId: string, writer: AgentWriter): Promise<Record<string, never>> {
  return write(agentId, 'archive', writer, {});
}

async function write<T>(agentId: string, action: string, writer: AgentWriter, payload: object): Promise<T> {
  return request<T>(`/api/agents/${encodeURIComponent(agentId)}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, client: writer.client }),
  });
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init });
  if (!response.ok) {
    const fallback = `Request failed (${response.status})`;
    let detail = '';
    try {
      const body = await response.text();
      if (body) {
        try {
          const data = JSON.parse(body);
          detail = typeof data.error === 'string' ? data.error : body;
        } catch {
          detail = body;
        }
      }
    } catch {
      // Keep the status-based fallback when the response body cannot be read.
    }
    throw new Error(detail ? `${fallback}: ${detail}` : fallback);
  }
  return response.json();
}
