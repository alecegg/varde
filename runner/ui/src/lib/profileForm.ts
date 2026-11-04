export type ProfileFields = { name: string; label: string; description: string };

export function validateProfile(fields: ProfileFields): Record<string, string> {
  const errors: Record<string, string> = {};
  if (fields.name.length < 1 || fields.name.length > 40) errors.name = 'Name must be 1 to 40 characters';
  if (fields.label.length < 1 || fields.label.length > 24) errors.label = 'Label must be 1 to 24 characters';
  if (fields.description.length > 280) errors.description = 'Description must be at most 280 characters';
  return errors;
}

export function serverErrors(body: unknown): Record<string, string> {
  if (!body || typeof body !== 'object' || !('errors' in body)) return {};
  const raw = (body as { errors?: unknown }).errors;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
}
