type RoleState = 'needs_you' | 'failed' | 'running' | 'idle' | 'done';

type RoleSummary = {
  role: string;
  state: RoleState;
  current: { title: string } | null;
  queued: number;
  needs_you: number;
  role_status_line?: string;
};

const NEEDS_YOU_LABEL_MAX = 9;

export function needsYouCountText(count: number): string {
  return count <= NEEDS_YOU_LABEL_MAX ? String(count) : `${NEEDS_YOU_LABEL_MAX}+`;
}

function itemTitle(summary: RoleSummary): string {
  return summary.current ? summary.current.title.slice(0, 40) : 'work';
}

export function statusText(summary: RoleSummary): string {
  if (summary.state === 'needs_you') return `Needs you: ${needsYouCountText(summary.needs_you)} approvals`;
  if (summary.state === 'failed') return `Failed on ${itemTitle(summary)}, ${summary.queued} in queue`;
  if (summary.state === 'running') return `Working on ${itemTitle(summary)}, ${summary.queued} in queue`;
  if (summary.state === 'idle') return summary.queued ? `Idle, ${summary.queued} in queue` : 'Idle';
  return 'Done';
}

export type RolePageCounts = { current: number; waiting: number; done: number };

export type RolePageSection = { key: keyof RolePageCounts; title: string; count: number };

const PAGE_SECTIONS = [
  { key: 'current', title: 'Current item' },
  { key: 'waiting', title: 'Waiting items' },
  { key: 'done', title: 'Recently done' },
] as const satisfies readonly { key: keyof RolePageCounts; title: string }[];

/** The role page keeps only sections that hold rows; zero-row sections become one empty card. */
export function rolePageSections(counts: RolePageCounts): RolePageSection[] {
  return PAGE_SECTIONS.filter((section) => counts[section.key] > 0).map((section) => ({ ...section, count: counts[section.key] }));
}

export function approvalRowText(count: number): string {
  return count === 1 ? 'Review 1 pending approval' : `Review ${needsYouCountText(count)} pending approvals`;
}

export function statusCardModel(summary: RoleSummary) {
  return {
    text: summary.role_status_line || statusText(summary),
    href: `/thread/${encodeURIComponent(summary.role)}`,
  };
}
