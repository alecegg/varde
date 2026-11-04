export function pair<A, B>(a: A, b: B): [A, B] {
  return [a, b];
}

export function constrained<T extends { id: number }>(item: T): number {
  return item.id;
}

export function options(a: number, config: { flag?: boolean } = {}): number {
  return config.flag ? a : 0;
}

export function callback(handler: (value: number) => void, value: number): void {
  handler(value);
}

export function union(a: number | string, b: number | string): string {
  return `${a}${b}`;
}

export function tuple([a, b]: [number, string]): string {
  return `${a}${b}`;
}

export function defaultsMixed(a: number, b = "x", c = true): string {
  return `${a}${b}${c}`;
}
