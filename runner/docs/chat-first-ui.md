# Chat-first runner UI

The runner UI centers on conversations. `/` shows items that need your attention
or an **All caught up** empty state. `/thread/<agentId>` opens an agent
conversation; the `manager` thread uses the manager bot's `main` conversation.
The avatar row switches between agents and the needs-you list. Agent details are
read-only at `/profile/<agentId>`. The header menu links to Needs you (`/`),
Conversations (`/thread/manager`), Plans (`/plans`) and Settings (`/settings`).
Mailbox (`/mailbox`) and Jobs (`/jobs`) remain available at their existing
routes.

| Previous route | Destination |
| --- | --- |
| `/home` | `/` |
| `/chat`, `/threads`, `/chats`, `/queue`, `/new-item` | `/thread/manager` |
| `/threads/<id>` | `/thread/<id>` |
| `/queue/<role>` | `/thread/<role>` |
| `/agents`, `/roles` | `/settings` |
| `/agents/profile/<id>` | `/profile/<id>` |

The manager conversation requires `[roles.manager-bot] enabled = true` in
`runner.toml`. This role is off by default. When disabled, the Manager chip has
no state dot, the conversation shows the existing disabled notice, and its
composer is disabled with instructions to enable the role. Other agent
conversations continue to work. The live runner configuration is managed by the
`2026-10-25-native-cutover` plan; this UI change does not edit it.
