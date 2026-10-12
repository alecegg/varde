//! Bounded provider execution for the hook dispatchers, which live in the app crate.

use std::sync::mpsc;
use std::thread;
use std::time::Duration;

/// Why [`within`] returned no result.
#[derive(Debug, PartialEq, Eq)]
pub enum WithinError {
    TimedOut,
    Panicked,
}

/// Run `work` on a worker thread; an error when it takes longer than `timeout`
/// or panics. A late result is dropped and the worker finishes on its own.
pub fn within<T: Send + 'static>(
    timeout: Duration,
    work: impl FnOnce() -> T + Send + 'static,
) -> Result<T, WithinError> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let _ = sender.send(work());
    });
    receiver.recv_timeout(timeout).map_err(|error| match error {
        mpsc::RecvTimeoutError::Timeout => WithinError::TimedOut,
        mpsc::RecvTimeoutError::Disconnected => WithinError::Panicked,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const LONG: Duration = Duration::from_secs(5);

    #[test]
    fn within_tells_a_panic_from_a_timeout() {
        assert_eq!(within(LONG, || 7), Ok(7));
        assert_eq!(
            within(LONG, || -> u8 { panic!("provider crashed") }),
            Err(WithinError::Panicked)
        );
        assert_eq!(
            within(Duration::from_millis(20), || {
                thread::sleep(Duration::from_millis(500));
            }),
            Err(WithinError::TimedOut)
        );
    }
}
