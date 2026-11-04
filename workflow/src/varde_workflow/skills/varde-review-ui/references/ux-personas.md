## 1. Self-hoster configuring a runner
who: Maintains a self-hosted VPS and wants to understand and control every setting.
wants: Reachable settings, honest errors, and a clear path from installation to a running agent.
viewport: both
tasks:
1. Find and change a runner setting; done when the new value is visible after saving.
2. Trigger a validation error and understand how to correct it; done when the error and recovery step are clear.
3. Start from the fresh install page and reach a running first agent; done when its running status is visible.

## 2. Mobile user checking agents
who: Uses a phone and wants to handle agent activity without learning a complex dashboard.
wants: A calm, quick interface with clear status, easy navigation, and simple approvals.
viewport: 390
Reference: compare the mobile end goal in `<working>/ui-reference/1.jpg`, `2.jpg`, and docs.x.ai/grok-bot/mobile (chat-first, one-line agent status, inline approval cards, pin/reorder).
tasks:
1. Find which agent needs attention; done when its status is understood without opening every agent.
2. Approve a request; done when the approval is confirmed and the agent state is clear.
3. Pin and reorder agents; done when the chosen order remains visible.

## 3. Desktop developer
who: Develops with several agents and values information density and configurable workflows.
wants: Scan agent activity quickly, filter it, and reach configuration without losing context.
viewport: desktop
tasks:
1. Scan many agents at once; done when active, idle, and blocked agents can be distinguished.
2. Filter the list to one agent state; done when only matching agents remain.
3. Open an agent configuration; done when its current settings are visible.
