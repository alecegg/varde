export type ConfigChoices = Record<string, {
  harnesses: string[];
  models: string[];
  reasoning_efforts: string[];
}>;

export const emptyTypesMessage = 'No model types in this configuration (legacy format). Saving role types converts it.';

export type TypeConfig = {
  name: string;
  harness: string;
  model: string;
  reasoning_effort: string;
  fallback: { harness: string; model: string; reasoning_effort: string }[];
};

export function choicesFor(choices: ConfigChoices, harness: string) {
  return choices[harness] ?? { harnesses: [], models: [], reasoning_efforts: [] };
}

export function harnessOptions(choices: ConfigChoices) {
  return Object.keys(choices).sort();
}

export function unavailableChoiceHarnesses(types: TypeConfig[], choices: ConfigChoices): string[] {
  return [...new Set(types.flatMap((item) => [item.harness, ...item.fallback.map((fallback) => fallback.harness)]).filter((harness) => {
    const options = choicesFor(choices, harness);
    return !options.models.length || !options.reasoning_efforts.length;
  }))];
}

export function typesFromItems(items: { key: string; value: unknown }[]): TypeConfig[] {
  const values = new Map(items.map(({ key, value }) => [key, value]));
  const names = [...new Set(items.flatMap(({ key }) => {
    const match = /^types\.([^.]+)\./.exec(key);
    return match ? [match[1]] : [];
  }))];
  return names.map((name) => ({
    name,
    harness: String(values.get(`types.${name}.harness`) ?? ''),
    model: String(values.get(`types.${name}.model`) ?? ''),
    reasoning_effort: String(values.get(`types.${name}.reasoning_effort`) ?? ''),
    fallback: (values.get(`types.${name}.fallback`) as TypeConfig['fallback'] | undefined) ?? [],
  }));
}

export function typeChanges(types: TypeConfig[]) {
  return Object.fromEntries(types.flatMap((type) => [
    [`types.${type.name}.harness`, type.harness],
    [`types.${type.name}.model`, type.model],
    [`types.${type.name}.reasoning_effort`, type.reasoning_effort],
    [`types.${type.name}.fallback`, type.fallback],
  ]));
}

export function moveFallback(fallbacks: TypeConfig['fallback'], index: number, offset: -1 | 1) {
  const target = index + offset;
  if (index < 0 || index >= fallbacks.length || target < 0 || target >= fallbacks.length) return fallbacks;
  const reordered = [...fallbacks];
  [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
  return reordered;
}

export function fallbackMoveAnnouncement(from: number, to: number): string {
  return `Fallback ${from} moved to position ${to}.`;
}

export function validateFallbacks(fallbacks: TypeConfig['fallback']) {
  return fallbacks.map((fallback) => {
    if (!fallback.harness) return 'Choose a harness.';
    if (!fallback.model) return 'Choose a model.';
    if (!fallback.reasoning_effort) return 'Choose an effort.';
    return '';
  });
}
