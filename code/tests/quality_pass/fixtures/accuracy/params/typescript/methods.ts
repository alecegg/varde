export class Store {
  constructor(
    private root: string,
    private size = 0,
  ) {}

  get(key: string): string | undefined {
    void this.root;
    void this.size;
    return key;
  }

  put(key: string, value: string): void {
    void key;
    void value;
  }

  items(): string[] {
    return [];
  }

  static fromConfig(config: { root: string }): Store {
    return new Store(config.root);
  }
}

export const arrowOne = (a: number) => a;
export const arrowTwo = (a: number, b: number) => a + b;
export const arrowRest = (...values: string[]) => values.length;

export function outer(x: number): number {
  function helper(y: number, z: number) {
    return y + z;
  }
  return helper(x, x);
}
