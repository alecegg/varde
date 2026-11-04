from collections import deque
from typing import Callable, Optional

WINDOW_SECONDS = 60


class Channel:
    def __init__(self, name: str, limit: int) -> None:
        self.name = name
        self.limit = limit
        self._send_times: deque[int] = deque()

    def is_limited(self, now: int) -> bool:
        self._discard_expired(now)
        return len(self._send_times) >= self.limit

    def record_send(self, now: int) -> None:
        self._send_times.append(now)

    def _discard_expired(self, now: int) -> None:
        cutoff = now - WINDOW_SECONDS
        while self._send_times and self._send_times[0] <= cutoff:
            self._send_times.popleft()


class Dispatcher:
    def __init__(
        self,
        channels: list[tuple[str, int]],
        send: Callable[[str, str], bool],
    ) -> None:
        self._channels = [Channel(name, limit) for name, limit in channels]
        self._send = send

    def dispatch(self, message: str, now: int) -> Optional[str]:
        for channel in self._channels:
            if self._try_send(channel, message, now):
                return channel.name
        return None

    def _try_send(self, channel: Channel, message: str, now: int) -> bool:
        if channel.is_limited(now):
            return False
        if not self._send(channel.name, message):
            return False
        channel.record_send(now)
        return True
