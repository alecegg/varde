---
type: pattern
description: Standard error envelope shape for API responses.
generated: { by: codex/gpt-5, at: 2026-06-01T00:00:00Z }
---

Wrap every error response in `{ error: { code, message } }`. Never return a
bare string or a raw exception body.
