#!/usr/bin/env bash
set -euo pipefail
cd "$EVAL_SANDBOX_DIR"

git init -q -b main
git config user.email "eval@example.com"
git config user.name "eval"

# A plain, unambiguous area: a real path, not a bare word, so eval 1 never
# hits the ambiguity check.
mkdir -p src/core/auth
cat > src/core/auth/session.ts <<'EOF'
export function validateSession(token: string): boolean {
  return token.length > 0;
}
EOF

# A bare-word area that is ALSO a valid git branch name below, so eval 2's
# "payments" ambiguity (git ref vs. feature-area keyword) is a real collision
# instead of an assumed one.
mkdir -p payments
cat > payments/invoice.ts <<'EOF'
export function chargeInvoice(amountCents: number): void {
  // charge logic
}
EOF


# Route handlers with no session middleware, so eval 4's "middleware vs.
# route handler" question has real code on both sides to compare.
mkdir -p src/routes
cat > src/routes/orders.ts <<'EOF'
import { validateSession } from "../core/auth/session";

export function getOrders(token: string) {
  if (!validateSession(token)) throw new Error("unauthorized");
  return [];
}
EOF

# A job queue with retry logic, for eval 5's "how does the retry logic work".
mkdir -p src/jobs
cat > src/jobs/queue.ts <<'EOF'
export function retry(fn: () => void, attempts: number): void {
  for (let i = 0; i < attempts; i++) {
    try {
      fn();
      return;
    } catch {
      // retry until attempts are exhausted
    }
  }
}
EOF

git add -A
git commit -q -m "Seed auth area, payments area, routes, and job queue"

git branch payments

# feature/rate-limiter diverges from main for eval 3's branch-vs-main diff.
git checkout -q -b feature/rate-limiter
mkdir -p src/middleware
cat > src/middleware/rate-limit.ts <<'EOF'
export function rateLimit(requestsPerMinute: number) {
  return (token: string) => true;
}
EOF
git add -A
git commit -q -m "Add rate-limiter middleware"
git checkout -q main
