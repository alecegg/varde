interface Channel {
  name: string;
  limit: number;
  sendTimes: number[];
}

type SendFn = (channel: string, message: string) => boolean;

const WINDOW_SECONDS = 60;

export class Dispatcher {
  private readonly channels: Channel[];
  private readonly send: SendFn;

  constructor(configs: { name: string; limit: number }[], send: SendFn) {
    this.channels = configs.map(({ name, limit }) => ({
      name,
      limit,
      sendTimes: [],
    }));
    this.send = send;
  }

  dispatch(message: string, nowSeconds: number): string | null {
    for (const channel of this.channels) {
      this.pruneExpiredSends(channel, nowSeconds);

      if (channel.sendTimes.length >= channel.limit) continue;

      // Failed attempts do not count toward the successful-send limit.
      if (!this.send(channel.name, message)) continue;

      channel.sendTimes.push(nowSeconds);
      return channel.name;
    }

    return null;
  }

  private pruneExpiredSends(channel: Channel, nowSeconds: number): void {
    const windowStart = nowSeconds - WINDOW_SECONDS;

    // The window is half-open: sends at the 60-second boundary have expired.
    while (
      channel.sendTimes.length > 0 &&
      channel.sendTimes[0] <= windowStart
    ) {
      channel.sendTimes.shift();
    }
  }
}
