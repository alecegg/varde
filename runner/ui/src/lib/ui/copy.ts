export const NOT_REPORTED = 'Not reported';

export function reportedValue(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  return value;
}

export function safeLabel(value: unknown, fallback = NOT_REPORTED): string {
  const label = reportedValue(value);
  if (!label) return fallback;
  if (
    label.startsWith('/') ||
    /^[a-z][a-z0-9+.-]*:\/\//i.test(label) ||
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(label) ||
    /^[0-9a-f]{24,}$/i.test(label)
  ) return fallback;
  return label;
}
