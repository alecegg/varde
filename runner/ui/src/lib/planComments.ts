import { api } from './queue';

export type CommentState = 'open' | 'resolved';
export type CommentKind = 'delivered' | 'saved';
export type PlanComment = {
  id: string;
  ts: string;
  target: string;
  text: string;
  state: CommentState | 'addressed';
  kind: CommentKind | 'sent' | 'stored';
  actor?: string;
  sender?: string;
  resolution_note?: string;
};

export function commentKind(kind: string | undefined): CommentKind {
  return kind === 'sent' || kind === 'delivered' ? 'delivered' : 'saved';
}

export function commentState(state: string | undefined): CommentState {
  return state === 'resolved' ? 'resolved' : 'open';
}

export async function addPlanComment(planId: string, target: string, text: string) {
  return api<{ comment: PlanComment }>(`/api/plans/${encodeURIComponent(planId)}/comments`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ target, text: text.trim() })
  });
}

export async function setPlanCommentState(planId: string, commentId: string, state: CommentState) {
  return api<{ comment: PlanComment }>(`/api/plans/${encodeURIComponent(planId)}/comments/${encodeURIComponent(commentId)}`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ state })
  });
}
