export function savedMessage(result: { restart_required: boolean }): string {
  return result.restart_required
    ? 'Saved. Restart the runner to apply it.'
    : 'Saved';
}
