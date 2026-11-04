import { describe, expect, it } from 'vitest';
import { appIconPath, headerTitle } from './navHeader';

describe('shared navigation header text', () => {
  it.each([
    ['/', 'Chats'],
    ['/chat', 'Chats'],
    ['/chat/needs', 'Needs action'],
    ['/thread/manager', 'Conversation'],
    ['/threads/thread-1', 'Conversation'],
    ['/settings', 'Settings'],
    ['/settings/model-types', 'Model Types'],
    ['/plans', 'Plans'],
    ['/plans/plan-1', 'Plan'],
    ['/profile/manager', 'Agent profile'],
    ['/jobs', 'Jobs'],
    ['/unknown', 'Varde'],
  ])('uses %s title on its route', (pathname, title) => {
    expect(headerTitle(pathname)).toBe(title);
  });

  it('uses the selected icon asset for the header', () => {
    expect(appIconPath('slate-bronze')).toBe('/favicon.svg');
    expect(appIconPath('dark')).toBe('/icons/dark/favicon-32.png');
  });
});
