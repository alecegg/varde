const labels: Record<string, string> = {
  address_bindings: 'address bindings',
  plan_status: 'plan status'
};

export function degradedSourceLabels(sources: string[]): string[] {
  return sources.flatMap((source) => labels[source] ? [labels[source]] : []);
}
