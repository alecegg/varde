//! Process-wide write accounting of logical bytes counted by the OS. Callers
//! should checkpoint WAL files and drop database connections before reading
//! the meter so pending writes are included.

/// A snapshot of the process-wide write counter.
pub struct WriteMeter {
    start: u64,
}

impl WriteMeter {
    /// Start measuring writes from the current process counter.
    pub fn start() -> Self {
        Self {
            start: current_bytes(),
        }
    }

    /// Return bytes written since this meter started.
    pub fn bytes(&self) -> u64 {
        current_bytes().saturating_sub(self.start)
    }
}

/// Whether this platform provides a supported process write counter.
pub fn available() -> bool {
    cfg!(any(target_os = "linux", target_os = "macos"))
}

/// Apply `VARDE_WRITE_BUDGET_SCALE` to a write budget (default 1.0).
/// Invalid, non-finite, or negative values are ignored.
pub fn scaled(limit: u64) -> u64 {
    scaled_with(
        limit,
        std::env::var("VARDE_WRITE_BUDGET_SCALE").ok().as_deref(),
    )
}

fn scaled_with(limit: u64, setting: Option<&str>) -> u64 {
    let factor = setting
        .and_then(|value| value.parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 0.0)
        .unwrap_or(1.0);
    ((limit as f64 * factor).min(u64::MAX as f64)) as u64
}

#[cfg(target_os = "linux")]
fn current_bytes() -> u64 {
    std::fs::read_to_string("/proc/self/io")
        .ok()
        .and_then(|contents| {
            contents
                .lines()
                .find_map(|line| line.strip_prefix("wchar:")?.trim().parse::<u64>().ok())
        })
        .unwrap_or(0)
}

#[cfg(target_os = "macos")]
fn current_bytes() -> u64 {
    let mut usage = std::mem::MaybeUninit::<libc::rusage_info_v4>::uninit();
    // SAFETY: `usage` points to writable storage for the requested v4 struct.
    let result = unsafe {
        libc::proc_pid_rusage(
            libc::getpid(),
            libc::RUSAGE_INFO_V4,
            usage.as_mut_ptr().cast(),
        )
    };
    if result == 0 {
        // SAFETY: the successful call initialized the requested struct.
        unsafe { usage.assume_init().ri_diskio_byteswritten }
    } else {
        0
    }
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn current_bytes() -> u64 {
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn write_meter_counts_synced_megabyte_and_scales_budget() {
        assert!(available(), "write meter is unavailable on this platform");
        let buffer = vec![0x5a; 1024 * 1024];
        let mut samples = Vec::new();
        for _ in 0..5 {
            let path = std::env::temp_dir().join(format!(
                "varde-write-meter-{}-{}",
                std::process::id(),
                NEXT_FILE.fetch_add(1, Ordering::Relaxed)
            ));
            let meter = WriteMeter::start();
            let mut file = File::create(&path).unwrap();
            file.write_all(&buffer).unwrap();
            file.sync_all().unwrap();
            drop(file);
            let written = meter.bytes();
            assert!(
                (1024 * 1024..2 * 1024 * 1024).contains(&written),
                "wrote {written} bytes"
            );
            fs::remove_file(path).unwrap();
            samples.push(written);
        }
        let min = *samples.iter().min().unwrap();
        let max = *samples.iter().max().unwrap();
        eprintln!("write-meter 1 MiB samples: {samples:?}; min={min}, max={max}");
        assert!(
            (max - min) * 100 < min * 10,
            "measurement spread exceeds 10%: {min}..{max}"
        );

        assert_eq!(scaled_with(100, Some("0.5")), 50);
        assert_eq!(scaled_with(100, Some("not-a-number")), 100);
        assert_eq!(scaled_with(100, None), 100);
    }
}
