export type PairingState = { enforced: boolean; paired: boolean; csrf: string | null };

export const CSRF_HEADER = 'x-varde-csrf';
const READ_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

type Fetch = typeof fetch;

export function isWrite(method: string | undefined): boolean {
  return !READ_METHODS.has((method ?? 'GET').toUpperCase());
}

export function isSameOrigin(url: string, origin: string): boolean {
  return url.startsWith('/') && !url.startsWith('//') || url.startsWith(`${origin}/`);
}

export function withCsrf(init: RequestInit | undefined, token: string | null): RequestInit | undefined {
  if (!token || !isWrite(init?.method)) return init;
  const headers = new Headers(init?.headers);
  headers.set(CSRF_HEADER, token);
  return { ...init, headers };
}

export function parsePairing(status: number, body: { enforced?: boolean; paired?: boolean; csrf?: string | null } | null): PairingState {
  if (status === 404) return { enforced: false, paired: true, csrf: null };
  return { enforced: body?.enforced !== false, paired: Boolean(body?.paired), csrf: body?.csrf ?? null };
}

export async function loadPairing(fetchImpl: Fetch): Promise<PairingState> {
  const response = await fetchImpl('/api/pairing', { cache: 'no-store' });
  const body = response.ok ? await response.json() : null;
  return parsePairing(response.status, body);
}

export async function submitPairing(fetchImpl: Fetch, code: string): Promise<PairingState> {
  const response = await fetchImpl('/api/pairing', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ code })
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.error === 'string' ? body.error : `Pairing failed (${response.status})`);
  }
  return parsePairing(response.status, await response.json());
}

/** Wrap fetch so same-origin writes carry the CSRF token the runner gave the paired browser. */
export function csrfFetch(base: Fetch, getToken: () => string | null, origin: string): Fetch {
  return (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    return base(input, isSameOrigin(url, origin) ? withCsrf(init, getToken()) : init);
  };
}
