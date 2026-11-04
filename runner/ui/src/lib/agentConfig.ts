import { roleType, type ModelType, type Role } from '../routes/roles/roles';

export type AgentConfig = { harness: string; model: string; effort: string; type: string };

export function effectiveConfig(
  roleName: string | null | undefined,
  roles: Record<string, Role>,
  types: Record<string, ModelType>,
): AgentConfig | null {
  if (!roleName) return null;
  const role = roles[roleName];
  if (!role) return null;
  const type = roleType(role, types);
  const config = types[type] ?? role;
  return {
    harness: config.harness,
    model: config.model,
    effort: config.reasoning_effort,
    type,
  };
}

export function summaryRows(config: AgentConfig | null): [string, string][] {
  return [
    ['Harness', config?.harness || 'Not set'],
    ['Model', config?.model || 'Not set'],
    ['Effort', config?.effort || 'Not set'],
    ['Role type', config?.type || 'Not set'],
  ];
}
