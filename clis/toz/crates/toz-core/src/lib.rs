//! toz-core: storage, chunking, capture pipeline, search, index and fetch for the `toz` CLI.

pub mod capture;
pub mod chunk;
pub mod config;
pub mod fetch;
pub mod index;
pub mod profile;
pub mod project;
pub mod rand;
pub mod raw;
pub mod redact;
pub mod script;
pub mod search;
pub mod store;
pub mod strategies;
pub mod streaming;
pub mod terms;

/// Short stable content fingerprint. Used for install manifests and script supersession keys.
pub fn content_hash(bytes: &[u8]) -> String {
    blake3::hash(bytes).to_hex()[..32].to_string()
}

pub use capture::{CaptureInput, Outcome, Preview};
pub use config::Config;
pub use project::Project;
pub use store::Store;

/// Counts allocations per thread so tests can assert that a reader is actually lazy.
///
/// Asserting "the JS heap survived" would pass while the host held the whole capture three times
/// over, which is the bug this exists to catch. Only compiled for tests.
#[cfg(test)]
pub mod alloc_probe {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::cell::Cell;

    thread_local! {
        static LIVE: Cell<isize> = const { Cell::new(0) };
        static PEAK: Cell<isize> = const { Cell::new(0) };
    }

    pub struct Counting;

    fn bump(delta: isize) {
        let _ = LIVE.try_with(|live| {
            let cur = live.get() + delta;
            live.set(cur);
            let _ = PEAK.try_with(|peak| {
                if cur > peak.get() {
                    peak.set(cur);
                }
            });
        });
    }

    unsafe impl GlobalAlloc for Counting {
        unsafe fn alloc(&self, l: Layout) -> *mut u8 {
            let p = unsafe { System.alloc(l) };
            if !p.is_null() {
                bump(l.size() as isize);
            }
            p
        }
        unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
            bump(-(l.size() as isize));
            unsafe { System.dealloc(p, l) }
        }
        unsafe fn realloc(&self, p: *mut u8, l: Layout, new: usize) -> *mut u8 {
            let np = unsafe { System.realloc(p, l, new) };
            if !np.is_null() {
                bump(new as isize - l.size() as isize);
            }
            np
        }
    }

    /// Zero the counters; peak then measures growth from this point on the current thread.
    pub fn reset() {
        LIVE.with(|l| l.set(0));
        PEAK.with(|p| p.set(0));
    }

    pub fn peak() -> usize {
        PEAK.with(|p| p.get().max(0) as usize)
    }
}

#[cfg(test)]
#[global_allocator]
static ALLOC_PROBE: alloc_probe::Counting = alloc_probe::Counting;
