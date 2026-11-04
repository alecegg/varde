type FlipDiff = { key: string; before: unknown; after: unknown };
type Role = { type?: string | null; harness?: string };

export function rolesAffected(diff: FlipDiff[], roles: Record<string, Role>): string[] {
  const sdkTypes = new Set(diff.flatMap(({ key, after }) => {
    const match = /^types\.([^.]+)\.harness$/.exec(key);
    return match && after === 'claude-sdk' ? [match[1]] : [];
  }));

  return Object.entries(roles)
    .filter(([, role]) => role.type && sdkTypes.has(role.type))
    .map(([name]) => name);
}

export function affectedText(roles: string[]): string {
  return roles.length
    ? `These roles will use Claude Code: ${roles.join(', ')}`
    : 'No roles need changes; this enables Claude Code for them.';
}
