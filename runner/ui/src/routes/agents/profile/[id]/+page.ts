import { redirect } from '@sveltejs/kit';

export const prerender = false;

export function load({ params }: { params: { id: string } }) {
  redirect(307, `/profile/${encodeURIComponent(params.id)}`);
}
