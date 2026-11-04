export const settingsSections = [
  { id: 'harnesses', label: 'Harnesses', group: 'Connections', summary: 'Connect the tools Varde can run with', icon: 'plug' },
  { id: 'runner', label: 'Runner', group: 'Runner', summary: 'Local service and workspace', icon: 'terminal' },
  { id: 'role-types', label: 'Role types', group: 'Models', summary: 'Defaults for each kind of work', icon: 'users' },
  { id: 'model-types', label: 'Model types', group: 'Models', summary: 'Model choices for each work type', icon: 'layers' },
  { id: 'display', label: 'Display', group: 'Appearance', summary: 'Appearance and theme', icon: 'sun' },
  { id: 'review', label: 'Daily session review', group: 'Maintenance', summary: 'Review recent agent work', icon: 'clock' },
  { id: 'status', label: 'Status', group: 'Maintenance', summary: 'Runner health and version', icon: 'pulse' },
] as const;

export type SettingsSectionId = (typeof settingsSections)[number]['id'];

export function activeSection(hash: string): SettingsSectionId | null {
  const id = hash.replace(/^#/, '');
  return settingsSections.find((section) => section.id === id)?.id ?? null;
}

export function groupedSections() {
  return settingsSections.reduce<Record<string, typeof settingsSections[number][]>>((groups, section) => {
    (groups[section.group] ??= []).push(section);
    return groups;
  }, {});
}
