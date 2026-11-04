export function groupByLength(text: string): Record<number, string[]> {
  const groups: Record<number, string[]> = {};
  for (const word of text.split(" ")) {
    if (word.length === 0) {
      continue;
    }
    groups[word.length] = groups[word.length] ?? [];
    groups[word.length].push(word);
  }
  return groups;
}
