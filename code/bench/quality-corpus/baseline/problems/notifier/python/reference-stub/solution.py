WINDOW = 60


class Dispatcher:
    def __init__(self, channels, send):
        self._channels = channels
        self._send = send
        self._sent = {name: [] for name, _ in channels}

    def dispatch(self, message, now):
        for name, limit in self._channels:
            recent = [t for t in self._sent[name] if t > now - WINDOW]
            self._sent[name] = recent
            if len(recent) >= limit:
                continue
            if self._send(name, message):
                recent.append(now)
                return name
        return None
