---
topic: varde-build/waiting-and-mail
version: 1
summary: Wait on running commands without polling; send one completion mail
---

- Do not poll a running command or agent; wait on completion or use one long
  wait.
- Workers send one completion mail. Skip receipt and progress acknowledgements,
  but send blocked or needs-user mail immediately.
