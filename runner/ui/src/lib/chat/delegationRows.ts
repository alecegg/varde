export type DelegationAuditRow = {
  id: number;
  phase: string;
  action: string;
  status: string;
  agent_id: string | null;
  plan_id: string | null;
  args_redacted?: string | null;
  ts: string;
};

export type DelegationRow = { id: string; text: string; ts: string };
type ChatLine = { role: string; text: string; created_at: string };

function readableTarget(row: DelegationAuditRow): string | null {
  if (row.plan_id) return `plan ${row.plan_id}`;
  if (!row.args_redacted) return null;
  try {
    const args: unknown = JSON.parse(row.args_redacted);
    if (!args || typeof args !== 'object' || Array.isArray(args)) return null;
    const values = args as Record<string, unknown>;
    for (const key of ['role', 'identity', 'plan']) {
      const value = values[key];
      if (typeof value === 'string' && value.trim()) return key === 'plan' ? `plan ${value.trim()}` : value.trim();
    }
  } catch { /* Older audit rows may not contain JSON arguments. */ }
  return null;
}

function launchLine(row: DelegationAuditRow, chatLines: ChatLine[]): string | null {
  const afterCall = chatLines
    .filter((line) => line.role === 'bot' && line.created_at >= row.ts && /\b(?:launch(?:ed|ing)?|delegat(?:ed|ing)?)\b/i.test(line.text))
    .sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
  return afterCall?.text.trim().replace(/\s+/g, ' ').slice(0, 180) || null;
}

export function delegationRows(auditRows: DelegationAuditRow[], chatLines: ChatLine[] = []): DelegationRow[] {
  const rows: DelegationRow[] = [];
  for (const row of auditRows) {
    if (row.phase !== 'call' || row.status !== 'allowed') continue;
    const verb = row.action === 'launch' ? 'Launched' : row.action === 'agent_stop' ? 'Stopped' : row.action === 'agent_archive' ? 'Archived' : null;
    if (!verb) continue;
    const targetLabel = readableTarget(row);
    const chatTarget = row.action === 'launch' ? launchLine(row, chatLines) : null;
    const target = chatTarget ?? targetLabel ?? row.agent_id;
    if (!target) continue;
    rows.push({ id: String(row.id), text: chatTarget ?? `${verb} ${target}`, ts: row.ts });
  }
  return rows;
}
