#!/usr/bin/env bash
set -euo pipefail

: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"
repo_root="$(cd "$EVAL_SANDBOX_DIR" && pwd -P)/project"
mkdir -p "$repo_root/src/auth"

cat > "$repo_root/src/lib.rs" <<'EOF'
pub mod auth;
pub mod metrics;
EOF

cat > "$repo_root/src/auth/mod.rs" <<'EOF'
pub mod coordinator;
pub mod session;
pub mod store;
EOF

cat > "$repo_root/src/auth/coordinator.rs" <<'EOF'
use crate::auth::{session, store};

use crate::auth::session::Session;
use crate::auth::store::TokenStore;

fn fetch_new_access_token() -> String {
    "fresh-access-token".to_owned()
}

pub fn refresh_auth_session(session: &mut Session, store: &mut TokenStore) {
    let token = fetch_new_access_token();
    session::replace_access_token(session, token.clone());
    store::persist_access_token(store, token);
}
EOF

cat > "$repo_root/src/auth/session.rs" <<'EOF'
#[derive(Default)]
pub struct Session {
    pub access_token: String,
}

pub fn replace_access_token(session: &mut Session, token: String) {
    session.access_token = token;
}
EOF

cat > "$repo_root/src/auth/store.rs" <<'EOF'
#[derive(Default)]
pub struct TokenStore {
    pub saved_access_token: Option<String>,
}

pub fn persist_access_token(store: &mut TokenStore, token: String) {
    store.saved_access_token = Some(token);
}
EOF

cat > "$repo_root/src/metrics.rs" <<'EOF'
#[derive(Default)]
pub struct MetricsCache {
    pub refreshed: bool,
}

pub fn refresh_metrics_cache(cache: &mut MetricsCache) {
    cache.refreshed = true;
}
EOF

# The index stays inside the runner-side fixture; no persistent watcher is started.
varde-code build --repo-root "$repo_root" >/dev/null
