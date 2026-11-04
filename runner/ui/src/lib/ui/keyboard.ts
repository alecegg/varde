export function keyboardSafe(node: HTMLElement) {
  const viewport = window.visualViewport;
  const originalPaddingBottom = node.style.paddingBottom;
  let lastInset: number | undefined;
  const update = () => {
    const inset = viewport
      ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
      : 0;
    if (inset === lastInset) return;
    lastInset = inset;
    node.style.setProperty('--keyboard-inset', `${inset}px`);
    if (node instanceof HTMLFormElement) {
      node.style.paddingBottom = inset > 0
        ? `calc(var(--space-3) + ${inset}px)`
        : originalPaddingBottom;
    }
    if (inset === 0) return;

    const field = document.activeElement;
    if (!(field instanceof HTMLElement) || !node.contains(field)) return;

    requestAnimationFrame(() => {
      const visibleBottom = viewport!.height + viewport!.offsetTop;
      const overflow = field.getBoundingClientRect().bottom - visibleBottom;
      if (overflow > 0) window.scrollBy(0, overflow);
    });
  };
  viewport?.addEventListener('resize', update);
  viewport?.addEventListener('scroll', update);
  update();
  return {
    destroy() {
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      node.style.removeProperty('--keyboard-inset');
      if (node instanceof HTMLFormElement) node.style.paddingBottom = originalPaddingBottom;
    },
  };
}
