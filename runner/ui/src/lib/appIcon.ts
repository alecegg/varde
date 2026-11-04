const iconLinks = 'link[rel~="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]';

export type AppIcon = 'slate-bronze' | 'dark';

export function iconPath(path: string, icon: AppIcon): string {
  const asset = path.split('/').at(-1) ?? path;
  return icon === 'dark' ? `/icons/dark/${asset}` : `/${asset}`;
}

export function iconUrl(path: string, version: string) {
  return `${path}?v=${encodeURIComponent(version)}`;
}

export function refreshIconLinks(icon: AppIcon) {
  const version = `${icon}-${Date.now()}`;
  document.querySelectorAll<HTMLLinkElement>(iconLinks).forEach((link) => {
    link.href = iconUrl(iconPath(new URL(link.href).pathname, icon), version);
  });
}
