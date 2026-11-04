export function shortenNeedsYou<T>(items: T[], limit = 3): { items: T[]; moreCount: number } {
  const visibleCount = Math.max(0, limit);
  return { items: items.slice(0, visibleCount), moreCount: Math.max(0, items.length - visibleCount) };
}

export function needsYouOptionLabel(option: unknown): string {
  if (typeof option === 'string') return option;
  if (!option || typeof option !== 'object') return '';
  const value = option as { label?: unknown; id?: unknown; title?: unknown };
  return [value.label, value.id, value.title].find((item): item is string => typeof item === 'string' && item.length > 0) ?? '';
}

export function needsYouAnswerText(text: string, option: string): string {
  return text.trim() || option;
}

export function mailboxItemAction(value: { kind?: unknown; type?: unknown }): 'permission' | 'question' | 'other' {
  if (value.kind === 'permission' || value.type === 'approval') return 'permission';
  if (value.kind === 'question' || value.type === 'question') return 'question';
  return 'other';
}

export function needsYouRefreshFailureMessage(error: string, degradedLabels: string[], rowCount: number): string | null {
  if (error) return error;
  if (rowCount > 0 || degradedLabels.length === 0) return null;
  return `Some data could not be refreshed (${degradedLabels.join(', ')}). Retry to check for items needing your attention.`;
}
