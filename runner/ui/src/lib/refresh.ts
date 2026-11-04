export const POLL_MS = 15_000;

// Run `refresh` when the page returns to the foreground and on a slow poll while visible.
// A suspended phone web app keeps a dead event stream that still looks open, so events alone go stale.
export function refreshWhenVisible(refresh: () => void, pollMs = POLL_MS): () => void {
  const refreshIfVisible = () => { if (document.visibilityState === 'visible') refresh(); };
  const timer = setInterval(refreshIfVisible, pollMs);
  document.addEventListener('visibilitychange', refreshIfVisible);
  window.addEventListener('focus', refreshIfVisible);
  window.addEventListener('pageshow', refreshIfVisible);
  return () => {
    clearInterval(timer);
    document.removeEventListener('visibilitychange', refreshIfVisible);
    window.removeEventListener('focus', refreshIfVisible);
    window.removeEventListener('pageshow', refreshIfVisible);
  };
}
