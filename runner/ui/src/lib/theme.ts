export type ThemeMode = 'system' | 'light' | 'dark';
export const themeModes: ThemeMode[] = ['system', 'light', 'dark'];

export function savedThemeMode(): ThemeMode {
  const saved = localStorage.getItem('varde:theme');
  return saved === 'light' || saved === 'dark' ? saved : 'system';
}

export function applyTheme(mode: ThemeMode) {
  localStorage.setItem('varde:theme', mode);
  const dark = mode === 'dark' || (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.dataset.themeMode = mode;
  window.dispatchEvent(new CustomEvent('runner:theme', { detail: mode }));
}
