export function noArgs(): number {
  return 0;
}

export function one(a: number): number {
  return a;
}

export function two(a: number, b: number): number {
  return a + b;
}

export function withDefaults(a: number, b = 1, c = 2): number {
  return a + b + c;
}

export function optional(a: number, b?: string): number {
  return b ? a : 0;
}

export function rest(a: number, ...values: number[]): number {
  return a + values.length;
}

export function destructured({ a, b }: { a: number; b: number }): number {
  return a + b;
}

export function arrayPattern([first, second]: number[]): number {
  return first + second;
}

export function generic<T>(value: T): T {
  return value;
}

export function annotated(a: number, b: string = "x"): void {
  void a;
  void b;
}

export function thisParam(this: Window, count: number): number {
  return count;
}

export function noTypeHints(a, b) {
  return a + b;
}
