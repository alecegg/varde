const WINDOW = 60;

interface Channel {
  name: string;
  limit: number;
}

export class Dispatcher {
  private sent = new Map<string, number[]>();
  private channels: Channel[];
  private send: (channel: string, message: string) => boolean;

  constructor(channels: Channel[], send: (channel: string, message: string) => boolean) {
    this.channels = channels;
    this.send = send;
  }

  dispatch(message: string, now: number): string | null {
    for (const { name, limit } of this.channels) {
      const recent = (this.sent.get(name) ?? []).filter((t) => t > now - WINDOW);
      this.sent.set(name, recent);
      if (recent.length >= limit) continue;
      if (this.send(name, message)) {
        recent.push(now);
        return name;
      }
    }
    return null;
  }
}
