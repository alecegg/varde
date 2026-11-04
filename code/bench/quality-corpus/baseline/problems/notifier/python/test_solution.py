import unittest

from solution import Dispatcher


class Sender:
    def __init__(self, failing=()):
        self.calls = []
        self.failing = set(failing)

    def __call__(self, channel, message):
        self.calls.append((channel, message))
        return channel not in self.failing


class NotifierTest(unittest.TestCase):
    def test_first_channel_used(self):
        sender = Sender()
        d = Dispatcher([("email", 5), ("sms", 5)], sender)
        self.assertEqual("email", d.dispatch("hi", 0))
        self.assertEqual([("email", "hi")], sender.calls)

    def test_limit_falls_back(self):
        d = Dispatcher([("email", 2), ("sms", 9)], Sender())
        self.assertEqual(
            ["email", "email", "sms"], [d.dispatch("m", t) for t in (0, 1, 2)]
        )

    def test_window_expires(self):
        d = Dispatcher([("email", 1), ("sms", 9)], Sender())
        self.assertEqual(
            ["email", "sms", "email"], [d.dispatch("m", t) for t in (0, 30, 61)]
        )

    def test_failed_send_falls_back(self):
        d = Dispatcher([("email", 5), ("sms", 5)], Sender(failing={"email"}))
        self.assertEqual("sms", d.dispatch("m", 0))

    def test_failed_send_keeps_quota(self):
        sender = Sender(failing={"email"})
        d = Dispatcher([("email", 1), ("sms", 9)], sender)
        self.assertEqual("sms", d.dispatch("m", 0))
        sender.failing.clear()
        self.assertEqual("email", d.dispatch("m", 1))

    def test_all_unavailable_returns_none(self):
        sender = Sender(failing={"email", "sms"})
        d = Dispatcher([("email", 5), ("sms", 5)], sender)
        self.assertIsNone(d.dispatch("m", 0))
        self.assertEqual(["email", "sms"], [c for c, _ in sender.calls])

    def test_boundary_at_window_edge(self):
        d = Dispatcher([("email", 1), ("sms", 9)], Sender())
        self.assertEqual("email", d.dispatch("m", 0))
        self.assertEqual("sms", d.dispatch("m", 59))
        self.assertEqual("email", d.dispatch("m", 60))

    def test_limited_channel_not_attempted(self):
        sender = Sender()
        d = Dispatcher([("email", 1), ("sms", 9)], sender)
        d.dispatch("a", 0)
        d.dispatch("b", 1)
        self.assertEqual([("email", "a"), ("sms", "b")], sender.calls)


if __name__ == "__main__":
    unittest.main()
