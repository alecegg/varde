const EMPTY_LENGTH = 0;
const SEPARATOR = " ";

export function groupByLength(text: string): Record<number, string[]> {
  return collect(words(text), groups());
}

function groups(): Record<number, string[]> {
  return {};
}

function collect(
  items: string[],
  buckets: Record<number, string[]>,
): Record<number, string[]> {
  for (const item of items) {
    if (hasContent(item)) {
      append(buckets, item);
    }
  }
  return buckets;
}

function append(buckets: Record<number, string[]>, item: string): void {
  bucket(buckets, size(item)).push(item);
}

function bucket(buckets: Record<number, string[]>, key: number): string[] {
  if (!buckets[key]) {
    buckets[key] = fresh();
  }
  return buckets[key];
}

function fresh(): string[] {
  return [];
}

function words(text: string): string[] {
  return text.split(SEPARATOR);
}

function hasContent(item: string): boolean {
  return size(item) > EMPTY_LENGTH;
}

function size(item: string): number {
  return item.length;
}
