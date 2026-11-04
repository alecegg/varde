# Calibration role reassignment

The call-resolution corpus reserves four former calibration repositories. They
remain in the verified manifest with no quality-corpus role. Eight newly
verified repositories provide the replacement calibration pool; Python and
TypeScript/JavaScript each meet the five-repository floor.

## Replacements

| Former calibration repo | Language | Replacement | SPDX | Pinned SHA | Why |
| --- | --- | --- | --- | --- | --- |
| `psf/requests` | Python | `pallets/click` | BSD-3-Clause | `2247b35ea1c47c727d7a06e51fa280e12a863ff6` | Active Python CLI library with focused source modules. |
| `expressjs/express` | JavaScript | `axios/axios` | MIT | `326843a3902d73c9f6af9bad7b55e2412566a251` | Active JavaScript HTTP client with a moderate source tree. |
| `prettier/prettier` | TypeScript | `colinhacks/zod` | MIT | `680d19f7d1e042e55934209caeb79bc843b94f44` | Active TypeScript validation library with source centered in TypeScript. |
| `typeorm/typeorm` | TypeScript | `fastify/fastify` | MIT | `e03b48ba3cd92dcbdafcb624579318e0f22176d2` | Active TypeScript web framework with a moderate source tree. |

## Additional calibration candidates

| Repository | Language | SPDX | Pinned SHA | Why |
| --- | --- | --- | --- | --- |
| `encode/httpx` | Python | BSD-3-Clause | `b5addb64f0161ff6bfe94c124ef76f6a1fba5254` | Active Python HTTP client; adds a second API-library style. |
| `python-attrs/attrs` | Python | MIT | `ee66e7274852438cc23d4240a1a9cd632fda8b52` | Active Python data-model library with focused source. |
| `pydantic/pydantic` | Python | MIT | `5adfeaaaea947f81f0f01868604f219084ec151a` | Active Python validation library with a substantial but bounded source tree. |
| `sindresorhus/got` | TypeScript | MIT | `05b4476913da39a47dd8e20d29e250f28b0a6dca` | Active TypeScript HTTP client with focused production code. |

All eight licenses were checked against the pinned root license text by the
corpus fetch verifier and the independent `cd_run.py` text check. Pins are the
default-branch tips captured by filtered HTTPS clones for this run.

`date-fns/date-fns` was evaluated but not retained: the pinned tree has no root
`LICENSE` or `COPYING` file recognized by the corpus verifier, so its license
could not be verified under the current policy.
