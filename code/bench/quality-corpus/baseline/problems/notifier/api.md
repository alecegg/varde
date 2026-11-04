# notifier API

Solution file: `solution.py` / `solution.ts` / `Solution.cs`.

- Python: `Dispatcher(channels: list[tuple[str, int]], send: Callable[[str, str], bool])`, `dispatch(message: str, now: int) -> str | None`.
- TypeScript: `export class Dispatcher` with constructor `(channels: {name, limit}[], send: (channel, message) => boolean)` and `dispatch(message, now): string | null`.
- C#: `class Dispatcher` with constructor `(List<(string Name, int Limit)> channels, Func<string, string, bool> send)` and `string? Dispatch(string message, int now)`.
