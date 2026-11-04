export type AppIconChoice = 'slate-bronze' | 'dark';

export function headerTitle(pathname: string): string {
  if (pathname === '/' || pathname === '/chat') return 'Chats';
  if (pathname === '/chat/needs') return 'Needs action';
  if (pathname.startsWith('/thread/') || pathname.startsWith('/threads/')) return 'Conversation';
  if (pathname === '/settings') return 'Settings';
  if (pathname === '/plans' || pathname.startsWith('/plans/')) return pathname === '/plans' ? 'Plans' : 'Plan';
  if (pathname.startsWith('/settings/')) {
    const section = pathname.split('/')[2] ?? '';
    return section.replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }
  if (pathname.startsWith('/profile/')) return 'Agent profile';
  if (pathname === '/jobs') return 'Jobs';
  return 'Varde';
}

export function appIconPath(icon: AppIconChoice): string {
  return icon === 'dark' ? '/icons/dark/favicon-32.png' : '/favicon.svg';
}

export type HeaderContext = {
  iconPath: string;
  menuExpanded: boolean;
  pageTitle: string;
  subtitle: string;
  backHref?: string;
  backLabel?: string;
  singleLineTitle: boolean;
};

export const headerContextKey = Symbol('runner-header-context');
