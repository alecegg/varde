import type { HomeSummary } from './homeList';

export type HomeResponse = { roles: HomeSummary[] };

export async function getHome(): Promise<HomeResponse> {
  const response = await fetch('/api/home', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
