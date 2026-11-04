# Widget matrix: rich sequence

A sign-in flow with a self-call, a group, an async hop and a note.

```ui
s1 = sequence(
  title: "Sign in",
  desc: "The browser signs a user in through the API, a cache and the user store.",
  actors: [
    {"id": "b", "label": "Browser"},
    {"id": "api", "label": "API"},
    {"id": "cache", "label": "Cache"},
    {"id": "db", "label": "User store"},
  ],
  steps: [
    {"from": "b", "to": "api", "text": "POST /login with the email and password"},
    {"from": "api", "to": "cache", "text": "lookup session"},
    {"from": "cache", "to": "api", "text": "miss", "kind": "return"},
    {"from": "api", "to": "db", "text": "find user by email", "group": "cache miss"},
    {"from": "db", "to": "api", "text": "user row", "kind": "return", "group": "cache miss"},
    {"from": "api", "to": "api", "text": "verify the password hash"},
    {"from": "api", "to": "cache", "text": "store session", "kind": "async"},
    {"from": "b", "to": "db", "text": "Passwords are never sent back.", "kind": "note"},
    {"from": "api", "to": "b", "text": "200 with a session cookie", "kind": "return"},
  ],
)
```

```ui
s2 = sequence(
  desc: "One actor calls itself.",
  actors: [{"id": "w", "label": "Worker"}],
  steps: [{"from": "w", "to": "w", "text": "retry with backoff"}],
)
```
