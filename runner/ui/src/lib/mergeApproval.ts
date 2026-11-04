export type ApprovalPlan = { id: string; status?: string; awaiting_user?: string | null; merge_state?: string; merge_approved_at?: string | null };
export function isMergeReady(plan: ApprovalPlan): boolean {
  return Boolean(plan.awaiting_user) && !plan.merge_approved_at && !['done', 'cancelled', 'complete', 'completed', 'concluded', 'abandoned', 'finished'].includes((plan.status ?? '').toLowerCase()) && !['approved_not_merged', 'merged'].includes(plan.merge_state ?? '');
}
export function validateNote(text: string): string | null {
  return text.length <= 500 ? null : 'Note must be 500 characters or fewer.';
}
export function approvalBody(note: string): { note: string | null } { return { note: note.trim() || null }; }
