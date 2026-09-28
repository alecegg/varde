//! Tiny non-cryptographic PRNG for handle generation. Not worth a dependency.

use std::cell::Cell;
use std::time::{SystemTime, UNIX_EPOCH};

thread_local! {
    static STATE: Cell<u64> = Cell::new(seed());
}

fn seed() -> u64 {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0x9E3779B97F4A7C15);
    let pid = std::process::id() as u64;
    let addr = &nanos as *const u64 as u64;
    nanos ^ pid.rotate_left(32) ^ addr.rotate_left(17)
}

/// splitmix64 step.
pub fn next_u64() -> u64 {
    STATE.with(|s| {
        let mut z = s.get().wrapping_add(0x9E3779B97F4A7C15);
        s.set(z);
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    })
}
