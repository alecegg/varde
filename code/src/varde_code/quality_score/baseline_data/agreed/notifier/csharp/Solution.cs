using System;
using System.Collections.Generic;
using System.Linq;

public class Dispatcher
{
    private const int WindowSeconds = 60;

    private readonly List<Channel> _channels;
    private readonly Func<string, string, bool> _send;

    public Dispatcher(List<(string Name, int Limit)> channels, Func<string, string, bool> send)
    {
        ArgumentNullException.ThrowIfNull(channels);
        _send = send ?? throw new ArgumentNullException(nameof(send));

        _channels = channels
            .Select(channel => new Channel(channel.Name, channel.Limit))
            .ToList();
    }

    public string? Dispatch(string message, int now)
    {
        foreach (var channel in _channels)
        {
            if (channel.IsLimitedAt(now))
                continue;

            if (!_send(channel.Name, message))
                continue;

            channel.RecordSend(now);
            return channel.Name;
        }

        return null;
    }

    private sealed class Channel
    {
        private readonly int _limit;
        private readonly List<int> _sendTimes = new();

        public Channel(string name, int limit)
        {
            Name = name;
            _limit = limit;
        }

        public string Name { get; }

        public bool IsLimitedAt(int now) =>
            _sendTimes.Count(time => time > now - WindowSeconds) >= _limit;

        public void RecordSend(int now) => _sendTimes.Add(now);
    }
}
