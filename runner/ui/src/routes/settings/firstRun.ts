export type FirstRunStep = { id: string; done?: boolean; hint: string; link: string };
export type FirstRunStatus = {
  data_root?: string | null;
  service?: { managed?: boolean; installed?: boolean } | null;
  harnesses?: { enabled?: boolean; binary_found?: boolean; login?: string }[] | null;
  checklist?: FirstRunStep[] | null;
};

const links: Record<string, string> = { data_root: '#runner', service: '#runner', harness: '#harnesses', roles: '/roles' };

export function stepLink(step: FirstRunStep): string { return links[step.id] ?? step.link; }

function usableHarness(harness: NonNullable<FirstRunStatus['harnesses']>[number]): boolean {
  const missing = harness.login === 'missing' || harness.binary_found === false;
  return Boolean(harness.enabled) && !missing;
}

function conditionHolds(stepId: string, status: FirstRunStatus): boolean {
  switch (stepId) {
    case 'data_root': return Boolean(status.data_root);
    case 'service': return Boolean(status.service?.installed || status.service?.managed);
    case 'harness': return (status.harnesses ?? []).some(usableHarness);
    default: return false;
  }
}

/** Tick each step when its visible condition holds, keeping backend-only conditions (roles). */
export function checklistSteps(status: FirstRunStatus): FirstRunStep[] {
  return (status.checklist ?? []).map((step) => ({ ...step, done: Boolean(step.done) || conditionHolds(step.id, status) }));
}
