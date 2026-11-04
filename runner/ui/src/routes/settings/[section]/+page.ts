import { redirect } from '@sveltejs/kit';
import { settingsSections } from '../settingsNav';

export function load({ params }: { params: { section: string } }) {
  const section = settingsSections.find((item) => item.id === params.section);
  if (!section) redirect(307, '/settings');
  return { section };
}

export function entries() {
  return settingsSections.map(({ id }) => ({ section: id }));
}
