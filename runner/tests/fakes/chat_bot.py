"""Scripted HTTP responses for browser tests of the chat page."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse


def message(seq: int, text: str, *, role: str = "bot", change_seq: int | None = None):
    return {
        "seq": seq,
        "change_seq": seq if change_seq is None else change_seq,
        "id": f"message-{seq}",
        "thread_key": "main",
        "reply_to": None,
        "role": role,
        "kind": None,
        "text": text,
        "link": None,
        "state": "final",
        "source_agent_id": None,
        "source_event_seq": None,
        "created_at": "2026-10-25T10:00:00Z",
    }


class FakeChatBot:
    """A deterministic chat API fake that can fail sends and script stream events."""

    def __init__(self, messages=()):
        self.messages = list(messages)
        self.posts: list[dict] = []
        self.streams: list[int] = []
        self.fail_posts = 0
        self.fail_history = False
        self.bot_state = "running"
        self.stream_events: list[tuple[str, dict]] = []
        self.stream_batches: list[list[tuple[str, dict]]] = []

    def route(self, route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        if parsed.path == "/api/chat" and request.method == "GET":
            if self.fail_history:
                route.fulfill(status=503, json={"error": "scripted history failure"})
                return
            query = parse_qs(parsed.query)
            before = int(query["before"][0]) if "before" in query else None
            rows = [
                row for row in self.messages if before is None or row["seq"] < before
            ]
            route.fulfill(
                json={
                    "messages": rows[-50:],
                    "latest_seq": self.messages[-1]["seq"] if self.messages else 0,
                    "thread": {
                        "key": "main",
                        "kind": "main",
                        "label": "Chat",
                        "state": self.bot_state,
                    },
                    "bot": {
                        "state": self.bot_state,
                        "context_pct": None,
                        "generation": 1,
                    },
                }
            )
            return
        if parsed.path == "/api/chat/messages" and request.method == "POST":
            payload = request.post_data_json
            self.posts.append(payload)
            if self.fail_posts:
                self.fail_posts -= 1
                route.fulfill(status=503, json={"error": "scripted failure"})
                return
            seq = len(self.messages) + 1
            self.messages.append(message(seq, payload["text"], role="user"))
            route.fulfill(status=202, json={"id": payload["client_msg_id"], "seq": seq})
            return
        if parsed.path == "/api/chat/stream":
            query = parse_qs(parsed.query)
            after = int(query.get("after", ["0"])[0])
            last_event_id = int(request.headers.get("last-event-id", after))
            self.streams.append(after)
            batch_index = len(self.streams) - 1
            events = (
                self.stream_batches[batch_index]
                if batch_index < len(self.stream_batches)
                else self.stream_events
            )
            frames = "".join(
                (f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(row)}\n\n")
                for kind, row in events
                for event_id in [row.get("change_seq", row.get("rev", after + 1))]
                if event_id > last_event_id
            )
            route.fulfill(status=200, content_type="text/event-stream", body=frames)
            return
        route.continue_()
