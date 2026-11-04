const SEPARATOR = ",";
const NAME = /^[a-z_][a-z0-9_]*$/;
const REPORT = `
name,value
alpha,1
`;

export class Lexer {
  private position = 0;

  constructor(
    private readonly text: string,
    private readonly keepWhitespace = false,
  ) {}

  peek(): string {
    return this.position >= this.text.length ? "" : this.text[this.position];
  }

  take(count = 1): string {
    const chunk = this.text.slice(this.position, this.position + count);
    this.position += count;
    return chunk;
  }
}

export function splitNames(raw: string, limit = 3): string[] {
  const names = raw
    .split(SEPARATOR)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  return limit > 0 ? names.slice(0, limit) : names;
}

export function render(names: string[], prefix = "item"): string {
  return names.map((name, index) => `${prefix}-${index}:${name}`).join(SEPARATOR);
}

export function isValid(name: string): boolean {
  return name.length > 0 && NAME.test(name);
}
