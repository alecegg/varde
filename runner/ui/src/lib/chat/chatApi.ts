import type { ChatMessage } from './chatState';

export type ChatThreadInfo = { key: string; kind: 'main' | 'instance'; label: string | null; state: string };
export type ChatBotInfo = { state: string; context_pct: number | null; generation: number };
export type ChatHistory = { messages: ChatMessage[]; latest_seq: number; thread: ChatThreadInfo; bot: ChatBotInfo };
export type ChatStreamEvent =
  | { type: 'message'; message: ChatMessage }
  | { type: 'delta'; id: string; rev: number; text_append: string }
  | { type: 'bot'; bot: ChatBotInfo };

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.error === 'string' ? body.error : `Chat request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const query = (thread: string, values: Record<string, string | number | undefined> = {}) => {
  const params = new URLSearchParams({ thread });
  for (const [key, value] of Object.entries(values)) if (value !== undefined) params.set(key, String(value));
  return params.toString();
};

export async function getHistory(thread: string, before?: number): Promise<ChatHistory> {
  return responseJson(await fetch(`/api/chat?${query(thread, { before, limit: 50 })}`));
}

export async function sendMessage(thread: string, id: string, text: string, replyTo?: string): Promise<{ id: string; seq: number }> {
  return responseJson(await fetch('/api/chat/messages', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ client_msg_id: id, text, thread, reply_to: replyTo ?? null })
  }));
}

export function openChatStream(thread: string, after: number, onEvent: (event: ChatStreamEvent) => void, onOpen: () => void, onError: () => void): () => void {
  const source = new EventSource(`/api/chat/stream?${query(thread, { after })}`);
  source.onopen = onOpen;
  source.onerror = onError;
  source.addEventListener('message', (event) => {
    try { onEvent({ type: 'message', message: JSON.parse((event as MessageEvent).data) as ChatMessage }); } catch { /* Ignore malformed events. */ }
  });
  source.addEventListener('delta', (event) => {
    try { onEvent({ type: 'delta', ...(JSON.parse((event as MessageEvent).data) as Omit<Extract<ChatStreamEvent, {type:'delta'}>, 'type'>) }); } catch { /* Ignore malformed events. */ }
  });
  source.addEventListener('bot', (event) => {
    try { onEvent({ type: 'bot', bot: JSON.parse((event as MessageEvent).data) as ChatBotInfo }); } catch { /* Ignore malformed events. */ }
  });
  return () => source.close();
}
