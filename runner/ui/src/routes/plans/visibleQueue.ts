export function visibleQueue<T>(plans: T[], expanded: boolean, pageSize = 20): T[] {
  return expanded ? plans : plans.slice(0, pageSize);
}
