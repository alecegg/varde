import { describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import { groupedSections, settingsSections } from './settingsNav.ts';

async function readSettingsFiles() {
  return {
    page: await readFile(new URL('./+page.svelte', import.meta.url), 'utf8'),
    content: await readFile(new URL('./sections/SettingsContent.svelte', import.meta.url), 'utf8'),
    nav: await readFile(new URL('./SettingsNav.svelte', import.meta.url), 'utf8'),
    route: await readFile(new URL('./[section]/+page.svelte', import.meta.url), 'utf8'),
  };
}

describe('settings navigation', () => {
  it('defines all seven sections in the approved groups', () => {
    expect(settingsSections.map(({ id }) => id)).toEqual([
      'harnesses', 'runner', 'role-types', 'model-types', 'display', 'review', 'status',
    ]);
    expect(Object.keys(groupedSections())).toEqual(['Connections', 'Runner', 'Models', 'Appearance', 'Maintenance']);
  });

  it('routes every section to a separate page and provides a back link', async () => {
    const { nav, route } = await readSettingsFiles();
    for (const { id } of settingsSections) {
      expect(nav).toContain("'/settings/' + section.id");
      const sectionView = await readFile(new URL(`./sections/${id}.svelte`, import.meta.url), 'utf8');
      expect(sectionView).toContain(`section="${id}"`);
    }
    expect(route).toContain('backHref="/settings"');
    expect(route).toContain("'role-types': RoleTypes");
  });

  it('keeps each section in the shared content view', async () => {
    const { content } = await readSettingsFiles();
    for (const { id } of settingsSections) expect(content).toContain(`id="${id}"`);
    expect(content).toContain('TypesCard');
    expect(content).toContain('RolesCard');
    expect(content).toContain('SdkFlipCard');
    expect(content).toContain('firstRun');
  });

  it('does not expose setup-only settings or personal settings in the overview', async () => {
    const { page, nav, content } = await readSettingsFiles();
    expect(settingsSections.map(({ id }) => id)).not.toEqual(expect.arrayContaining(['guard', 'policy', 'hosts']));
    expect(nav).toContain('data-settings-row={section.id}');
    expect(page + nav + content).toContain('App icon');
    expect(content).toContain('userSettings');
  });

  it('recognizes every section', () => {
    expect(settingsSections).toHaveLength(7);
    expect(settingsSections.find(({ id }) => id === 'model-types')?.summary).toBe('Model choices for each work type');
  });
});
