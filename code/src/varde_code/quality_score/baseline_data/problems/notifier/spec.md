# notifier behaviour spec

A dispatcher has channels in fallback order, each with a limit of sends per rolling 60-second window, and a `send(channel, message)` callback that returns true on success. `dispatch(message, now)` (integer seconds) tries channels in order and returns the name of the channel that sent, or none. A channel is skipped (its send is not called) when it already has `limit` successful sends with time `t > now - 60`. A failed send does not count toward the limit and the next channel is tried.

1. The first channel is used when it is free; send receives that channel name and the message.
2. With email limit 2, dispatches at 0, 1, 2 go to email, email, sms.
3. The window expires: email limit 1 sends at 0, sms at 30, email again at 61.
4. When send fails for a channel the next channel is used.
5. A failed send does not consume quota: email fails at 0 (sms is used), then succeeds at 1.
6. When every channel fails or is limited the result is none, and every channel not limited was tried in order.
7. Boundary: a send at 0 still counts at 59 but not at 60.
8. A limited channel is not attempted: email limit 1, two dispatches give send calls email then sms.
